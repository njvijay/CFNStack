#!/bin/bash -x

PROJECT_BASE=.
RUN=$1
ACTION=${RUN:-apply}

cfnstack  -y "$WORKSPACE"/environments/PMPCARE/care_cfn.yaml -a $ACTION
rc=$?
[[ $rc -eq 0 ]] && exit 0 || exit 1 
