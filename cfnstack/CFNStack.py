import logging
import simplejson
import boto3
from botocore.exceptions import ClientError
from copy import deepcopy

"""
CFNStack class provides methods to handle individual cloudformation stacks.
It reads and parse parameters defined in YAML file stack definition.
It can evaluate cloudformation templates
It can check whether dependent stack is available
It can read parameters(both input and output parameters) from existing stack
"""
class CFNStack(object):

    def __init__(self,stack_glue_name,aws_session,name,environment,params,template_name,region,sns_topic_arn,tags=None,depends_on=None):
        self.logger = logging.getLogger(__name__)
        if stack_glue_name == name:
            self.cfn_stack_name = name
        else:
            self.cfn_stack_name = '%s-%s-%s' % (stack_glue_name,environment,name)

        self.stack_glue_name = stack_glue_name
        self.aws_session = aws_session
        self.name = name
        self.environment = environment
        self.yaml_params = params
        self.params = []
        self.template_name = template_name
        self.template_body = ''
        self.tags = []
        if depends_on is None:
            self.depends_on = None
        else:
            self.depends_on = []
            for dep in depends_on:
                if dep == stack_glue_name:
                    self.depends_on.append(dep)
                else:
                    self.depends_on.append("%s-%s-%s" % (stack_glue_name,environment,dep))

        self.region = region
        self.sns_topic_arn = sns_topic_arn

        if tags is None:
            self.tags = []
        else:
            for key,value in tags.items():
                temp_dict = {}
                temp_dict['Key'] = key
                temp_dict['Value'] = value
                self.tags.append(temp_dict)

        # try:
        #     open(template_name, 'r')
        # except:
        #     self.logger.critical("Failed to open template file '%s' for Stack '%s'" % (self.template_name,self.name))
        #     exit(1)

        if self.yaml_params and type(self.yaml_params) is not dict:
            self.logger.critical("Parameters for stack %s must be of type dict no %s" % (self.name, type(self.yaml_params)))
            exit(1)

        self.cfn_stacks = {}
        self.cfn_stacks_resources = {}

    def exists_in_cfn(self,current_cf_stacks):
        """
        Check if this stack exists in amazon cloudformation
        """

        for stack in current_cf_stacks:
            if str(stack.stack_name) == self.cfn_stack_name:
                return stack

        return False

    def dependencies_met(self,current_cf_stacks):
        if self.depends_on is None:
            return True

        for dep in self.depends_on:
            dep_met = False
            for stack in current_cf_stacks:
                if str(stack.stack_name) == dep:
                    dep_met  = True
            if not dep_met:
                return False
        return True

    def populate_params(self,current_cf_stacks):

        if self.yaml_params is None:
            self.params = []
            return True

        if self.dependencies_met(current_cf_stacks):
            for param_name, param_val in self.yaml_params.items():
                temp_param_dict = {}
                temp_param_dict['ParameterKey'] = param_name

                if type(param_val) is dict:
                    temp_param_dict['ParameterValue'] = self._parse_param(param_name, param_val)
                    temp_param_dict['UsePreviousValue'] = param_val.get('usepreviousvalue', False)
                    self.params.append(temp_param_dict)
                elif type(param_val) is list:
                    param_list = []
                    for item in param_val:
                        if type(item) is dict:
                            param_list.append(self._parse_param(param_name, str(item['value'])))
                    self.params[param_name] = ','.join(param_list)
                    temp_param_dict['ParameterValue'] = ','.join(param_list)
                    temp_param_dict['UsePreviousValue'] = param_val.get('usepreviousvalue', False)
                    self.params.append(temp_param_dict)
            #pprint(self.params)
            return True
        else:
            return False

    def _parse_param(self, param_name, param_dict):
        if 'value' in param_dict :
            return str(param_dict['value'])
        elif ('source' in param_dict and 'type' in param_dict and 'variable' in param_dict):
            if param_dict['source'] == self.stack_glue_name:
                source_stack = param_dict['source']
            else:
                source_stack =  ("%s-%s-%s" % (self.stack_glue_name,self.environment,param_dict['source']))

            return self.get_value_from_cf(
                source_stack=source_stack,
                var_type=param_dict['type'],
                var_name=param_dict['variable']
            )
        else:
            self.logger.critical("Error in yaml file, can't parse parameter %s for %s stack",param_name,self.name)
            exit(1)

    def get_cf_stack(self,stack, resources=False):
        if not resources:
            if stack not in self.cfn_stacks:
                try:
                    cloudformation = self.aws_session.resource("cloudformation")
                    self.cfn_stacks[stack] = cloudformation.Stack(stack)
                except ClientError as exception:
                    self.logger.critical("Client ERROR: %s" % exception)
                    exit(1)

            return self.cfn_stacks[stack]
        else:
            if stack not in self.cfn_stacks_resources:
                #cloudformation = boto3.resource("cloudformation")
                the_stack = self.get_cf_stack(stack=stack, resources=False)
                self.cfn_stacks_resources[stack] = the_stack.resource_summaries.all()
            return self.cfn_stacks_resources[stack]


    def get_value_from_cf(self,source_stack,var_type,var_name):
        the_stack = self.get_cf_stack(stack=source_stack)
        try:
            if var_type == 'parameter':
                for param in the_stack.parameters:
                    if str(param['ParameterKey']) == var_name:
                        return str(param['ParameterValue'])
            elif var_type == 'output':
                for output in the_stack.outputs:
                    if str(output['OutputKey']) == var_name:
                        return str(output['OutputValue'])
            elif var_type == 'resource':
                for res in self.get_cf_stack(stack=source_stack, resources=True):
                    if str(res.logical_resource_id) == var_name:
                        return str(res.physical_resource_id)
            else:
                self.logger.critical("Error: invalid var_type passed to get_value_from_cd, needs to be 'parameter','resource' or 'output'. Not %s" % (var_type))
                exit(1)
        except ClientError as exception:
            self.logger.critical("Error calling Cloudformation API : "+str(exception))
            exit(1)

    def read_template(self):
        """
        Open and parse the json template for this stack
        """
        try:
            template_file = open(self.template_name,'r')
            template = simplejson.load(template_file)
        except Exception as exception:
            self.logger.critical("Cannot parse %s template for stack %s. Error %s", self.template_name,self.name,exception)
            exit(1)
        self.template_body = simplejson.dumps(template, sort_keys=True,indent=2,separators=(',',':'),)
        return True

    def get_params_tuples(self):
        """
        Convert param dict to array of tuples needed by boto
        """
        tuple_list=[]
        if len(self.params) > 0:
            for param in list(self.params.keys()):
                tuple_list.append((param,self.params[param]))
        return tuple_list

    def template_uptodate(self,current_cf_stacks):
        """
        Check if stack is up to date with cloudformation.
        Return true if template matches what's in cloudformatio,false if not
        """
        cf_stack = self.exists_in_cfn(current_cf_stacks)
        if cf_stack:
            cf_client = self.aws_session.client('cloudformation')
            cf_temp_dict = cf_client.get_template(StackName=self.cfn_stack_name)['TemplateBody']
            cf_stack_temp_dict = simplejson.loads(self.template_body)
            #cf_temp_dict = simplejson.loads(cf_temp_body)
            if cf_temp_dict == cf_stack_temp_dict:
                return True
        return False

    def params_uptodate(self, current_cf_stacks):
        """
        Check if parameters in stack are up to date with cloudformation

        """
        cf_stack = self.exists_in_cfn(current_cf_stacks)
        if not cf_stack:
            return False

        if cf_stack.parameters is None:
            stack_param_len = 0
        else:
            stack_param_len = len(cf_stack.parameters)

        if self.params is None:
            self_param_len = 0
        else:
            self_param_len = len(self.params)

        #If number of params in CF and this stack obj don't match then it needs updating
        if stack_param_len != self_param_len:
            self.logger.debug("New and Old parameter lists are different lengths for %s", self.name)
            return False

        cf_stack_param = cf_stack.parameters
        stack_param = deepcopy(self.params)

        for templ_param in stack_param:
            templ_param.pop('UsePreviousValue')
            if templ_param in cf_stack.parameters:
                continue
            else:
                self.logger.debug("Parameter has been changed for stack %s, update will be invoked with new parameter", self.name)
                return False
        return True