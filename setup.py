from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name='opentronsfastapi',
    version='0.1.0',
    url='https://github.com/Koeng101/opentronsfastapi',
    author='Keoni Gandall, Tim Dobbs',
    author_email='keoni@sporenetlabs.com, timdobbs@gmail.com',
    description='opentronsfastapi is package for building FastAPIs that run protocols on an Opentrons',
    long_description=long_description,
    packages=find_packages()    
)
