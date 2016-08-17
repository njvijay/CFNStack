#!/usr/bin/env python

#Entry program of this project.

import sys
from os.path import dirname,abspath

BIN_DIR = dirname(abspath(__file__))
ROOT_DIR = dirname(BIN_DIR)
sys.path.insert(0,ROOT_DIR)

from cfnstack import main

main()