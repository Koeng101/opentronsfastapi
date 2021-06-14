import math
import asyncio
from os import name, stat
import time
import datetime
import threading
import sqlite3
import inspect
import hashlib
import opentrons.execute as oe
import opentrons.simulate as os
import opentrons.config
from typing import List
from functools import wraps

from fastapi import FastAPI, APIRouter, Depends

default_app = FastAPI()
default_routes = APIRouter()

global opentrons_env
if opentrons.config.IS_ROBOT:
    opentrons_env = oe
else:
    opentrons_env = os

# The current_run_id is the protocol in the activity log that is currently running.
global current_run_id

# Setup sqlite3 lock
conn = sqlite3.connect("lock.db")
c = conn.cursor()
table_sql = """
BEGIN;
CREATE TABLE IF NOT EXISTS lock (
    id INT PRIMARY KEY,
    active BOOL NOT NULL DEFAULT false,
    locked_by INTEGER REFERENCES activity_log(id)
);
CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start INTEGER NOT NULL,
    end INTEGER,
    ot2_function TEXT NOT NULL,
    version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('RUNNING', 'FAILED', 'COMPLETED')),
    status_message TEXT
);
INSERT OR IGNORE INTO lock(id) VALUES (1);
UPDATE lock SET active = 0, locked_by = NULL WHERE id=1;
COMMIT;
"""
c.executescript(table_sql)
conn.close()

# Robotic locks
def lock_state():
    conn = sqlite3.connect("lock.db")
    c_lock = conn.cursor()
    c_lock.execute("SELECT active, locked_by FROM lock WHERE id=1")
    lock_state = c_lock.fetchone()
    d = {"active": lock_state[0], "locked_by": lock_state[1]}
    conn.close()
    return d

def get_lock(func):
    conn = sqlite3.connect("lock.db")
    c_lock = conn.cursor()
    c_lock.execute("SELECT active, locked_by FROM lock WHERE id=1")
    lock_state = c_lock.fetchone()

    if lock_state[0] == False:
        # Acquire the lock
        c_lock.execute("INSERT INTO activity_log(start,ot2_function,version,status,status_message) VALUES (?,?,?,?,?)", (int(time.time()), func.__name__, get_protocol_hash(func), "RUNNING", "Executed"))
        c_lock.execute("UPDATE lock SET active = 1, locked_by=? WHERE id=1", (c_lock.lastrowid,))
        global current_run_id
        current_run_id = c_lock.lastrowid
        conn.commit()
        conn.close()
        return c_lock.lastrowid
    conn.close()
    return False # Fail to acquire the lock

def unlock(lock_id, status, status_message):
    conn = sqlite3.connect("lock.db")
    c_lock = conn.cursor()
    c_lock.execute("UPDATE activity_log SET status = ?, status_message = ?, end = ? WHERE id = ? AND status != ?", (status, status_message, int(time.time()), lock_id, "FAILED"))
    c_lock.execute("UPDATE lock SET active = 0, locked_by='' WHERE id=1")
    conn.commit()
    conn.close()

def get_protocol_hash(func):
    func_string = inspect.getsource(func)
    func_hash = hashlib.sha256(func_string.encode('utf-8')).hexdigest()
    return func_hash

# https://gist.github.com/amirasaran/e91c7253c03518b8f7b7955df0e954bb
class BaseThread(threading.Thread):
    def __init__(self, callback=None, callback_args=None, *args, **kwargs):
        target = kwargs.pop('target')
        super(BaseThread, self).__init__(target=self.target_with_callback, *args, **kwargs)
        self.callback = callback
        self.method = target
        self.args = args
        self.kwargs = args
        self.callback_args = callback_args

    def target_with_callback(self, *args, **kwargs):
        try:
            self.method(*args, **kwargs)
        except Exception as e:
            conn = sqlite3.connect("lock.db")
            c_lock = conn.cursor()
            global current_run_id
            c_lock.execute("UPDATE activity_log SET status = ?, status_message = ?, end = ? WHERE id = ?", ("FAILED", str(e), str(time.time()), current_run_id))
            conn.commit()
            conn.close()
        if self.callback is not None:
            self.callback(*self.callback_args)

class OT_Flags:
    """
    Container for flags that can be added to a protocol and need to be parsed a special way.
    Each flag has a name that is referenced in the protocol parameters, and a FastAPI.Depends
    function that is passed to FastAPI when that name is referenced. When a function is passed
    to the parse method of the object, that function is checked to see if its parameters
    include any of the defined flags and, if so, the names of those parameters are added to
    the param_names attribute. This lets us know that those parameters must be treated
    specially, but don't require that the route use any particular keywords for their parameter
    names.
    """
    param_names = dict()
    flag_functions = dict()

    def get_flags(self):
        return list(self.flag_functions.values())

    def add_flag(self, flag_name, func_to_pass):
        setattr(self, flag_name, func_to_pass)
        self.flag_functions[func_to_pass] = flag_name

    #Checks route for special parameters labeled as relevant to opentrons_execute
    def parse(self, func):
        for param_name in inspect.signature(func).parameters:
            default_val = inspect.signature(func).parameters[param_name]._default
            try:
                flag = self.flag_functions[default_val]
                self.param_names[flag] = param_name
            except KeyError:
                pass
        return self.param_names

ot_flags = OT_Flags()
    
# Pass a void func to FastAPI as a placeholder until we can load a context into it
def void_func():
    pass
ot_flags.add_flag('protocol_context', Depends(void_func))

def report_version(version_only:bool = False):
    return version_only
ot_flags.add_flag('protocol_version_flag', Depends(report_version))


#Decorator that executes the function in a seperate thread
def opentrons_execute(msg = "Execution initiated", apiLevel='2.9'):
    def outer(func):
        @wraps(func)
        async def inner(*args, **kwargs):
            route_flags = ot_flags.parse(func)
            
            #Option to return just version hash if specified.
            if 'protocol_version_flag' in route_flags and kwargs[route_flags['protocol_version_flag']]==True:
                return {"Protocol": func.__name__, "ver": get_protocol_hash(func)}

            try:
                ctx_name = route_flags['protocol_context']
                assert ctx_name is not None
            except AssertionError:
                return {"Error": "Must pass a protocol context with my_param = opentronsfastapi.ot_flags.protocol_context"}

            lock = get_lock(func)
            if lock == False:
                return {"Message": "App currently locked"}

            # Since we have acquired the lock, we can reset global variable opentrons_env
            global opentrons_env
            ot = opentrons_env
            try:
                opentrons_env = os
                ctx = opentrons_env.get_protocol_api(apiLevel)
                kwargs[ctx_name] = ctx
                func(*args, **kwargs)
            except Exception as e:
                unlock(lock, "FAILED", "Failed on simulation.")
                return {"Message": "Failed on simulation. Got error message: {}".format(str(e)), "id": lock, "ver":get_protocol_hash(func)}
            opentrons_env = ot
            ctx = opentrons_env.get_protocol_api(apiLevel)
            ctx.home()
            kwargs[ctx_name] = ctx

            BaseThread(target=func, callback=unlock, callback_args=(lock, "COMPLETED", "Completed protocol successfully."), args=args, kwargs=kwargs).start()
            return {"Message": msg, "id": lock, "ver":get_protocol_hash(func)}
        return inner
    return outer


### Test funcs ####

@default_routes.get("/status/{run_id}")
def read_root(run_id: int):
    conn = sqlite3.connect("lock.db")
    c_lock = conn.cursor()
    c_lock.execute("SELECT status, status_message, start, end FROM activity_log WHERE id = ?", (run_id,))
    rows = c_lock.fetchall()
    for row in rows:
        status = row[0]
        status_message = row[1]
        start = int(row[2])
        execution_time = None
        if status == "FAILED" or status == "COMPLETED":
            execution_time = int(row[3]) - int(row[2])
    return {"status": status, "status_message": status_message, "started":datetime.datetime.fromtimestamp(start).strftime("%H:%M:%S. %A %d. %B %Y"), "execution_time": execution_time}

@default_routes.get("/test/unlock")
def test_unlock():
    unlock()

@default_routes.get("/test/lock")
@opentrons_execute(msg="Lock acquired for 10 seconds. Will be instant if not executing on real machine")
def test_lock_func(protocol = ot_flags.protocol_context):
    protocol.delay(10)

@default_routes.get("/test/lock_state")
def test_lock_state_func():
    return lock_state()

@default_routes.get("/test/home")
@opentrons_execute(msg="Lock acquired until home completes")
def test_home_func(protocol = ot_flags.protocol_context):
    pass
