# Example

```python3
from fastapi import FastAPI
from pydantic import BaseModel
import opentronsfastapi as otf

app = FastAPI()
app.include_router(otf.default_routes)

class DispenseWell(BaseModel):
    address: str

@app.post("/api/procedure/demo_procedure")
@otf.opentrons_execute(apiLevel='2.8')
def demo_procedure(dispenseWell:DispenseWell,
                   version = otf.ot_flags.protocol_version_flag,
                   protocol = otf.ot_flags.protocol_context
                  ):

    plate = protocol.load_labware("corning_96_wellplate_360ul_flat", 1)
    tip_rack = protocol.load_labware("opentrons_96_filtertiprack_20ul", 2)
    p20 = protocol.load_instrument("p20_single_gen2", "left", tip_racks=[tip_rack])

    p20.pick_up_tip()

    p20.aspirate(10, plate.wells_by_name()['A1'])
    p20.dispense(10, plate.wells_by_name()[dispenseWell.address])

    p20.drop_tip()
```

### Usage notes
There are three main touchpoints for most users:
- `@opentrons_execute()` Decorate your route with this function to have it executed on the OT2. There are two optional parameters:
    - `apiLevel` specifies the apiLevel that the OT2 should use when executing your function. Default is '2.9'
    - `msg` specifies the message that should be returned to the requesting server when protocol successfully _initiates_
- `opentronsfastapi.ot_flags.protocol_context` Every protocol **must** specify the variable that will be passed the Protocol Context by setting some value equal to this object in the parameters. This parameter will not be exposed to the API
- `opentronsfastapi.ot_flags.protocol_version_flag` Optionally, you may set a parameter equal to this obejct. This will expose an option in the API to query the protocol version without actually running the protocol. Protocol versions are reported as hashes of the code, so you can quickly determine if any of the protocol text has changed from what you expected.

# opentronsfastapi

opentronsfastapi is a library that allows for FastAPIs to be easily deployed onto Opentrons liquid handling robots (OT2) with robotic protocols. The protocols can be parameterized, allowing complex robotic functions to take place. Communication is done over HTTP via a REST API, and execution of the protocols begins immediately, allowing the OT2 to work as part of a larger lab management system, or simply allowing the user to build a user interface that suits their needs better than the stock options Opentrons provides.

For example, a biofoundry might have the following components for successfully executing a protocol:
1. A job queue that lists the tasks to be done
2. A system-level execution manager that decides what job to do next and passes the job to an appropriate robot
3. A client on the robot that receives job requests and, if accepted, initiates execution on the robot
4. A low-level layer that converts job instructions to the acutation of motors

opentronsfastapi specifically helps with #3.

## Features
opentronsfastapi:
- (done) Allows API endpoints to be wrapped with a decorator for execution on an Opentrons robot
- (done) Manages robot state - if the robot is busy, then job requests are refused until the robot work is complete, and an error code is returned to the requestor
- (done) Can report the state of the robot to a requestor, via API endpoint
- (done) Can report the protocol version the robot will use, in the form of a unique hash, via an API endpoint
- (done) Allows the API to be accessed by any arbitrary tool, as long as POST requests are sent in the right format
- (todo) Can be deployed on stock OT2's without special tools

## Limitations
- Works at the level of a single robot, and is naive of other robots. However, it can be deployed on multiple robots, which can then be managed by a supervisor.

## Todo
- Better and clearer exception handling of errors
- Automatic recongition of being deployed on a robot (users shouldn't have to set the `opentrons_env` global variable)
- Simple git deployment onto robots
- Hash returns of any individual protocol

## Install with systemd
```bash
export IP=xxx.xxx.x.xxx
ssh root@$IP 'mount -o remount,rw /'
scp opentronsfastapi.service root@$IP:/etc/systemd/system
ssh root@$IP 'systemctl enable opentronsfastapi'
ssh root@$IP 'reboot'
```

# Contributors
- Thank you Tim Dobbs for writing most of the README, adding essential wrappers, and generally bringing this project into reality.
