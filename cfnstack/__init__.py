#!/usr/bin/env python

"""
Entry program for CFNStack project. This program evaluates parameters passed and invoke respective methods to perform an action
"""

import logging

import argparse

from cfnstack.StackGlue import StackGlue


def main():
    """
    Entry function for cfnstack.py
    """
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument('-y', '--yamlfile', dest='yamlfile', required=True,
                            help="The yaml file where stacks,params & dependency definition exists")
    arg_parser.add_argument('-a', '--action', dest='action', required=True,
                            choices=['apply','update','createcs','listcs','applycs','deletecs','delete'],
                            help="Action to be performed : apply - Create Cloudformation stacks, update - Update CF stacks (Better use change sets)"
                                 ", createcs - Create Change sets on given stack, listcs - List Change sets on given Stack, applycs - Apply Change Sets on given stack,"
                                 " deletecs - Delete change sets on given stack, delete - Delete Cloudformation stacks")
    arg_parser.add_argument('-l','--logging', dest='loglevel', required=False, default="info",
                            choices=['critical','error','warning','info' or 'debug'], help='Log level for output messages,''critical,error,warning,info,debug')
    arg_parser.add_argument('-L','--botolog',dest='botolog',required=False,default='critical',
                            choices=['critical','error','warning','info' or 'debug'], help='Log level for boto,''critical,error,warning,info,debug')
    arg_parser.add_argument('-s','--stack',dest='stackname',required=False, help='Stack Name. It can be called with individual action also')
    arg_parser.add_argument('-c', '--changesetname', dest='changesetname', required=False,
                            help='Change Set name to be applied on stack to update')
    arg_parser.add_argument('-p', '--profile', dest='profile', required=False,
                            help='AWS configure profile name to be used. If not provided, default profile will be used. This could be useful to use with federated IAM USER')

    args = arg_parser.parse_args()

    #Validate Mandatory parameters

    #Validating action parameter. Actions in commented variable will be developed for future enhancement
    #valid_actions = ['apply','check','update','delete','watch']
    valid_actions = ['apply', 'update', 'createcs', 'listcs', 'applycs','deletecs','delete']
    if args.action not in valid_actions:
        print("Invalid action provided, must be one of '%s'" % (", ".join(valid_actions)))
        exit(1)

    #Validate yamlfile exists or not
    try:
        open(args.yamlfile,'r')
    except IOError as exception:
        print("Can't read YAML file %s:%s" % (args.yamlfile,exception))
        exit(1)

    #Configure log level for application
    numeric_level = getattr(logging,args.loglevel.upper())
    boto_numeric_level = getattr(logging,args.botolog.upper())
    if not isinstance(numeric_level,int):
        print('Invalid Log Level for output message - %s' % args.loglevel)
        exit(1)
    FORMAT = "%(asctime)s:%(levelname)s:%(name)s-%(module)s:%(message)s"
    logging.basicConfig(level=numeric_level,format=FORMAT)
    logger = logging.getLogger(__name__)

    if not isinstance(boto_numeric_level,int):
        print('Invalid boto log level - %s' % args.botolog)
        exit(1)
    logging.getLogger('boto').setLevel(level=boto_numeric_level)

    glued_stack = StackGlue(args.yamlfile,args.profile)
    glued_stack.sort_cf_stacks_by_deps()

    #Print info
    logger.info("Project Name: %s", glued_stack.name)
    logger.info("Found %s Cloud formation stacks in provided yaml.", len(glued_stack.cf_stacks))
    logger.info("Cloudformation stacks are processed in the following order: %s", [x.name for x in glued_stack.stack_objs])
    for stack in glued_stack.stack_objs:
        logger.debug("%s depends on %s", stack.name, stack.depends_on)

    # Perform action
    if args.action == 'apply':
        glued_stack.apply(args.stackname)
    if args.action == 'delete':
        glued_stack.delete(args.stackname)
    if args.action == 'update':
        glued_stack.update(args.stackname)
    if args.action == 'listcs':
        glued_stack.listcs(args.stackname)
    if args.action == 'applycs':
        if args.changesetname != None and args.stackname != None:
            glued_stack.applycs(args.stackname, args.changesetname)
        else:
            logger.critical("Change set name and stackname must be provided. Use option \"-c\" or \"--changesetname\" for changesetname, \"-s\" or \"--stackname\" for stackname .")
            exit(1)
    if args.action == 'createcs':
        if args.changesetname != None and args.stackname != None:
            glued_stack.createcs(args.stackname, args.changesetname)
        else:
            logger.critical("Change set name and stackname must be provided. Use option \"-c\" or \"--changesetname\" for changesetname, \"-s\" or \"--stackname\" for stackname .")
            exit(1)
    if args.action == 'deletecs':
        if args.changesetname != None and args.stackname != None:
            glued_stack.deletecs(args.stackname, args.changesetname)
        else:
            logger.critical("Change set name and stackname must be provided. Use option \"-c\" or \"--changesetname\" for changesetname, \"-s\" or \"--stackname\" for stackname .")
            exit(1)



if __name__ == '__main__':
    main()
