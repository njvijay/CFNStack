import logging
import os
import time

import boto3
import pystache
import yaml
from botocore.exceptions import NoCredentialsError, ClientError

from cfnstack.CFNStack import CFNStack

"""
StackGlue glues cloudformation stacks together and provides ability to create/destroy stacks based on dependency defined in YAML file
StackGlue class has methods to read YAML file where cloudformation stacks are listed with dependencies
and sort the cloudformation stacks based on dependencies and action methods to create, update and delete
cloudformation stacks listed in YAML file
"""

class StackGlue(object):
    def __init__(self, yamlfile, profile):
        self.logger = logging.getLogger(__name__)

        if profile and not profile.isspace():
            config_profile = profile
        else:
            config_profile = 'default'

        yamlconfig = open(yamlfile, 'r')
        render_yaml = pystache.render(yamlconfig.read(), dict(os.environ))
        self.stackDict = yaml.safe_load(render_yaml)

        # There will be only one global stack name
        toplevel_stack_count = len(self.stackDict.keys())
        if toplevel_stack_count != 1:
            error_message = ("Need one and only global stack name at the top level, found %s")
            self.logger.critical(error_message % toplevel_stack_count)
            exit(1)

        self.name = list(self.stackDict.keys())[0]

        if 'region' in self.stackDict[self.name]:
            self.region = self.stackDict[self.name]['region']
        else:
            self.logger.critical("No region mentioned in the stack. Please specify region")
            exit(1)

        # Verifying account id of key and stack account id

        # if 'account_id' in self.stackDict[self.name]:
        #     iam = boto3.resource('iam')
        #     current_user_arn = iam.CurrentUser().arn
        #     account_id = current_user_arn.split(':')[4]
        #
        #     if account_id != str(self.stackDict[self.name]['account_id']):
        #         self.logger.critical(
        #             'Account ID of the stack does not match the account ID of the aws credentials used.')
        #         exit(1)

        # Get the environment
        if 'environment' in self.stackDict[self.name]:
            self.environment = self.stackDict[self.name]['environment'].lower()
        else:
            # Assign default as DEV
            self.environment = 'dev'

        # Get and verify SNS topic
        self.sns_topic_arn = self.stackDict[self.name].get('sns-topic-arn', [])
        if isinstance(self.sns_topic_arn, str):
            self.sns_topic_arn = [self.sns_topic_arn]
        for topic in self.sns_topic_arn:
            if topic.split(':')[3] != self.region:
                self.logger.critical('SNS Topic %s is not in the %s region' % (topic, self.region))
                exit(1)

        self.global_tags = self.stackDict[self.name].get('tags', {})
        # print(self.global_tags['project'])

        # Array for holding CFNStack objects
        self.stack_objs = []

        self.cf_stacks = list(self.stackDict[self.name]['stacks'].keys())

        # Get all existing cloudformation stack details
        try:
            self.aws_session = boto3.Session(profile_name=config_profile)
            self.cfn_conn = self.aws_session.resource("cloudformation")
            self.cfn_all_stacks = self.cfn_conn.stacks.all()
        except NoCredentialsError as exception:
            self.logger.critical("No Credentials found for connecting to cloudformation: %s" % exception)
            exit(1)

        for stack_name in self.cf_stacks:
            one_stack = self.stackDict[self.name]['stacks'][stack_name]
            if type(one_stack) is dict:
                if one_stack.get('disable', False):
                    self.logger.warning("Stack %s is disabled by configuration, skipping..." % stack_name)
                    continue

            local_sns_arn = one_stack.get('sns-topic-arn', self.sns_topic_arn)
            if isinstance(local_sns_arn, str):
                local_sns_arn = [local_sns_arn]

            for topic in local_sns_arn:
                if topic.split(':')[3] != self.region:
                    self.logger.critical(
                        "SNS topic '%s' for Stack '%s' is not in the '%s' region " % (topic, stack_name, self.region))
                    exit(1)

            local_tags = one_stack.get('tags', {})

            self.merged_tags = self.global_tags.copy()
            self.merged_tags.update(local_tags.items())

            # Add static application tag
            self.merged_tags['Environment'] = self.environment.upper()

            if 'cf_template' in one_stack:
                self.stack_objs.append(
                    CFNStack(
                        stack_glue_name=self.name,
                        aws_session = self.aws_session,
                        name=stack_name,
                        environment=self.environment,
                        params=one_stack.get('params'),
                        template_name=one_stack['cf_template'],
                        region=self.region,
                        sns_topic_arn=local_sns_arn,
                        depends_on=one_stack.get('depends'),
                        tags=self.merged_tags
                    )
                )

    # Sort Cloudformation stacks by dependencies listed in YAML file
    def sort_cf_stacks_by_deps(self):
        """
        Sort the array of stack_objs so they are in dependency order
        """
        sorted_stacks = []
        dep_graph = {}
        no_deps = []

        # Add all stacks without dependencies in no_deps
        for stack in self.stack_objs:
            if stack.depends_on is None:
                no_deps.append(stack)
            else:
                dep_graph[stack.name] = stack.depends_on[:]

        while len(no_deps) > 0:
            stack = no_deps.pop()
            sorted_stacks.append(stack)
            for node in list(dep_graph):
                for deps in dep_graph[node]:
                    if stack.cfn_stack_name == deps:
                        dep_graph[node].remove(stack.cfn_stack_name)
                        if len(dep_graph[node]) < 1:
                            for stack_obj in self.stack_objs:
                                if stack_obj.name == node:
                                    no_deps.append(stack_obj)
                            del dep_graph[node]
        if len(dep_graph) > 0:
            self.logger.critical(
                "could not resolve dependency order. Either circular dependency or dependency on stack not in yaml file")
            exit(1)
        else:
            self.stack_objs = sorted_stacks
            return True

    # Apply - Create stacks if does not exists in AWS cloudformation and update the stack with updated template if stack already exists in cloudformation
    def apply(self, stack_name=None):
        for stack in self.stack_objs:
            if stack_name and stack.name != stack_name:
                continue
            self.logger.info("Determining whether stack needs to be created or updated")

            if not stack.exists_in_cfn(self.cfn_all_stacks):
                self.logger.info("Stack %s does not exists in CloudFormation. Stack %s is going to be created" % (
                stack.name, stack.name))
                self.create(stack.name)
            else:
                self.logger.info(
                    "Stack %s exists in CloudFormation. Checking wheter there is any change in the cloudformation template or parameters" % stack.name)
                self.update(stack.name)

    # Create cloudformation stack and this function is called from apply.
    def create(self, stack_name=None):
        """
        Create all stacks in the yaml file based on dependency order.
        Any stack already exists skip the stack creation
        """

        for stack in self.stack_objs:
            if stack_name and stack.name != stack_name:
                continue
            self.logger.info("Starting checks for creation of stack %s" % stack.name)

            if stack.exists_in_cfn(self.cfn_all_stacks):
                self.logger.critical("Stack %s already exists in cloudformation, skipping..." % stack.name)
            else:
                if stack.dependencies_met(self.cfn_all_stacks) is False:
                    self.logger.critical("Dependencies for stack %s is not met and exiting..." % stack.name)
                    exit(1)
                if not stack.populate_params(self.cfn_all_stacks):
                    self.logger.critical("Could not determine correct parameters for stack %s" % stack.name)
                    exit(1)

                stack.read_template()
                self.logger.info("Creating: %s, and its parameters : %s" % (stack.cfn_stack_name, stack.params))
                try:
                    self.cfn_conn.create_stack(
                        StackName=stack.cfn_stack_name,
                        TemplateBody=stack.template_body,
                        Parameters=stack.params,
                        Capabilities=['CAPABILITY_IAM'],
                        NotificationARNs=stack.sns_topic_arn,
                        OnFailure='DELETE',
                        Tags=stack.tags
                    )
                except Exception as exception:
                    self.logger.critical("Creating stack %s failed. Error: %s" % (stack.cfn_stack_name, exception))
                    exit(1)

                create_result = self.watch_events(stack.cfn_stack_name, "CREATE_IN_PROGRESS")
                if create_result != "CREATE_COMPLETE":
                    self.logger.critical("Stack did not create correctly, status is now %s" % create_result)
                    exit(1)

                self.logger.info("Finished creating stack: %s" % stack.cfn_stack_name)
                self.cfn_all_stacks = self.cfn_conn.stacks.all()

    # Update cloudfromation stack if already exists in AWS cloudformation
    def update(self, stack_name=None):
        for stack in self.stack_objs:
            if stack_name and stack.name != stack_name:
                continue
            self.logger.info("Starting checks for update of stack %s" % stack.name)

            if not stack.exists_in_cfn(self.cfn_all_stacks):
                self.logger.critical(
                    "Stack %s does not exists in cloudformation, can't update non-existing stack, skipping..." % stack.name)
            else:
                if stack.dependencies_met(self.cfn_all_stacks) is False:
                    self.logger.critical("Dependencies for stack %s is not met and exiting..." % stack.name)
                    exit(1)
                if not stack.populate_params(self.cfn_all_stacks):
                    self.logger.critical("Could not determine correct parameters for stack %s" % stack.name)
                    exit(1)

                stack.read_template()

                template_up_to_date = stack.template_uptodate(self.cfn_all_stacks)
                params_up_to_date = stack.params_uptodate(self.cfn_all_stacks)

                self.logger.info("Stack is up to date: %s" % (template_up_to_date and params_up_to_date))

                if template_up_to_date and params_up_to_date:
                    self.logger.info("Stack '%s' is already up to date with cloudformation. Skipping..." % stack.name)
                else:
                    self.logger.info("Template or parameter for stack %s has changed." % stack.name)
                    self.logger.info("Starting update of stack %s with parameters: %s" % (stack.name, stack.params))

                    # Validate template step can be added here

                    try:
                        self.cfn_conn.Stack(stack.cfn_stack_name).update(
                            TemplateBody=stack.template_body,
                            Parameters=stack.params,
                            Capabilities=['CAPABILITY_IAM'],
                            NotificationARNs=stack.sns_topic_arn
                        )
                    except ClientError as exception:
                        if (str(exception.response['Error']['Message']) == "No updates are to be performed."):
                            self.logger.error(
                                "CloudFormation has no updates to perform on resources of stack %s. Continue with next stack if exists..." % stack.name)
                            continue
                        else:
                            self.logger.critical(
                                "Updating stack %s failed. Error: %s" % (stack.cfn_stack_name, exception))
                            exit(1)

                    update_result = self.watch_events(
                        stack.cfn_stack_name, [
                            "UPDATE_IN_PROGRESS",
                            "UPDATE_COMPLETE_CLEANUP_IN_PROGRESS"])
                    if update_result != "UPDATE_COMPLETE":
                        self.logger.critical(
                            "Stack didn't update correctly, status is now %s"
                            % update_result)
                        exit(1)

                    self.logger.info(
                        "Finished updating stack: %s" % stack.cfn_stack_name)

            # avoid getting rate limited
            time.sleep(2)

    #Delete cloudformation stack
    def delete(self, stack_name=None):
        """
        Delete all the stacks from cloudformation.
        Delete the stack in reverse dependency order
        """
        for stack in reversed(self.stack_objs):
            if stack_name and stack.name != stack_name:
                continue
            self.logger.info("Starting checks for creation of stack %s" % stack.name)

            if not stack.exists_in_cfn(self.cfn_all_stacks):
                self.logger.critical("Stack %s does not exist in cloudformation, skipping..." % stack.name)
            else:
                self.logger.info("Starting to delete stacks %s" % stack.name)
                try:
                    self.cfn_conn.Stack(stack.cfn_stack_name).delete()
                except  Exception as exception:
                    self.logger.critical("Deleting stack %s failed. Error: %s" % (stack.cfn_stack_name, exception))
                    exit(1)

                delete_result = self.watch_events(stack.cfn_stack_name, "DELETE_IN_PROGRESS")

                if (delete_result != "DELETE_COMPLETE" and delete_result != "STACK_GONE"):
                    self.logger.critical("Stack didn't get deleted correctly, Status is now %s", delete_result)
                    exit(1)

                self.logger.info("Finished deleting Stack: %s", stack.cfn_stack_name)
                self.cfn_all_stacks = self.cfn_conn.stacks.all()

    # Watch cloudformation events for all action
    def watch_events(self, stack_name, while_status):
        """
        Stay and watch cloudformation events till 'while_status'
        """
        cfstack_obj = self.cfn_conn.Stack(stack_name)
        first_events = []

        try:
            cfstack_obj.reload()
            events = self.cfn_conn.Stack(stack_name).events.all()
        except ClientError as exception:
            if (str(exception.response['Error']['Message']) == "Stack with id %s does not exist" % (stack_name)):
                return "STACK_GONE"

        for evt in first_events:
            first_events.append(evt)

        self.logger.info("All events for the stack - %s :", self.name)

        try:
            for evt in reversed(first_events):
                self.logger.info("%s %s %s %s %s %s" % (
                    evt.timestamp.isoformat(),
                    evt.resource_status,
                    evt.resource_type,
                    evt.logical_resource_id,
                    evt.physical_resource_id,
                    evt.resource_status_reason,
                ))
        except ClientError as exception:
            self.logger.critical("Error reading events list : " + str(exception))

        status = str(cfstack_obj.stack_status)

        while status in while_status:
            self.logger.info("Fetching new events for the stack - %s :", self.name)
            new_events = []
            event_to_log = []
            try:
                cfstack_obj.reload()
                events = self.cfn_conn.Stack(stack_name).events.all()
            except ClientError as exception:
                if (str(exception.response['Error']['Message']) == "Stack with id %s does not exist" % (stack_name)):
                    return "STACK_GONE"

            for evt in events:
                new_events.append(evt)

            event_to_log = [evt for evt in new_events if evt not in first_events]

            try:
                for evt in reversed(event_to_log):
                    self.logger.info("%s %s %s %s %s %s" % (
                        evt.timestamp.isoformat(),
                        evt.resource_status,
                        evt.resource_type,
                        evt.logical_resource_id,
                        evt.physical_resource_id,
                        evt.resource_status_reason,
                    ))
            except ClientError as exception:
                self.logger.critical("Error reading events list : " + str(exception))

            try:
                status = str(cfstack_obj.stack_status)
            except ClientError as exception:
                if (str(exception.response['Error']['Message']) == "Stack with id %s does not exist" % (stack_name)):
                    return "STACK_GONE"

            first_events = new_events

            self.logger.info("Waiting 5 Sec to fetch log for the stack - %s :", self.name)

            time.sleep(5)

        return status
