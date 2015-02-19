__author__ = 'nicole'

import yaml
import os.path

#read configuration file
curie_map = None

#load the curie mapping file, if it exists.
#it isn't required, but is necessary for most resources
if os.path.exists("conf/curie_map.yaml"):
    with open("conf/curie_map.yaml") as yaml_file:
        curie_map = yaml.load(yaml_file)
        print("INFO: Finished loading curie maps:",curie_map)

elif os.path.exists("../conf/curie_map.yaml"):
    with open("../conf/curie_map.yaml") as yaml_file:
        curie_map = yaml.load(yaml_file)
        print("INFO: Finished loading curie maps:",curie_map)


def get():
    return curie_map