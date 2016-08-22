# CFNStack

AWS Cloudformation template is a great way to maintain your aws infrastructure as code. As your infrastructure grows, cloudformation gets complex. Cloudformation template becomes monolithic and very difficult to maintain. No easy method found to modularize cloudformation template. Amazon recommends few methods to modularize cloudformation.

1. **Nested stacks** - You can call reusable CF template from other template. But, it mandates to keep reusable CF template in S3. I found maintaining CF template in S3 is little tedious in code maintenance point of view and continuous integration point of view.
2. **Using Lambda** - Writing AWS lambda backed custom resources - Every templates may need to have lambda function to read properties of CF stack you are referring to. It becomes very complex when you start referring resources from multiple templates.

CFNStack is a python utility which tries to solve above issues and allows you to glue multiple cloudformation templates together with defined dependencies. CFNStack uses YAML configuration file to modularize CFN templates and allows each stack to refer other dependent stacks for parameters, outputs or resource ids. CFNStack is written using python 3. This is clone of [cumulus](https://github.com/cotdsa/cumulus)  project with many improvements like using boto3 library, python 3 etc.,

### Prerequisites:

python3 with pip, setuptools, boto3,pystache,yaml packages

Any linux distribution (not tested in windows) Or use Vagrant.
vagrantfile is available in the repository

[awscli](https://aws.amazon.com/cli/)


### Installation Procedure

Here is the installation Procedure

Clone the repo in your favorite directory

[CFNStack repository ](https://github.com/njvijay/CFNStack.git)

Install CFNStack with setuptools (python3 should be used )

sudo python3 setup.py install

Next, AWS credentials are required to run cfnstack program. Boto3 python package should work with credential setup run by aws cli configure command.

aws configure

Enter "AWS Access Key ID", "AWS Secret Access Key" and "Default region name"

### cfnstack usage

```
usage: cfnstack [-h] -y YAMLFILE -a ACTION [-l {critical,error,warning,info}]
                [-L {critical,error,warning,info}] [-s STACKNAME]

optional arguments:
  -h, --help            show this help message and exit
  -y YAMLFILE, --yamlfile YAMLFILE
                        The yaml file where stacks,params & dependency
                        definition exists
  -a ACTION, --action ACTION
                        Action to be performed : apply, check, delete or watch
  -l {critical,error,warning,info}, --logging {critical,error,warning,info}
                        Log level for output
                        messages,critical,error,warning,info,debug
  -L {critical,error,warning,info}, --botolog {critical,error,warning,info}
                        Log level for boto,critical,error,warning,info,debug
  -s STACKNAME, --stack STACKNAME
                        Stack Name. It can be called with individual action
                        also
```

### YAML file structure for cfnstack

Check input YAML file sample in **templates/sample_stack.yaml**. Each section of the sample file described below

#### Header

This is where you would defined project name and common tag names which can be used for all the stacks in the project.

Code snippets from above yaml file

```
sample:
    region: us-east-1
    environment: dev
    tags:
        project : Test
        charge_code : AAABCCC
        Owner : PROJECT-A
```
Sample - Replace this with your project name. This will be used as part of Cloudformation stacks tag name

region - Specify the AWS region where you want to run your cloudfromation templates.

environment - It could be your envionrment like dev or qa or prod. This will be used as part of Cloudformation stacks tag name

tags - tags for your cloudformation. This will be inherited to all cloudformation stacks which you bring up part of this project. Please note there is a limitation of number of tags you specify for the aws resources. Every stack you define part of this project can have its own tag + these tags.

#### Stack

You would define individual cloudformation stack details in this section including location of the cloudformation template, dependency if it depends on other stack's resource, parameters etc.,

Example YAML file has 3 stacks defined. VPC is the first stack which does not have any dependencies. Bastion is depending on a resource from VPC. That is nothing but vpcid. vpcid is required to define subnet and bring bastion host ec2 instance. Also, NAT is depended on VPC for vpcid.

Bastion --> VPC <-- NAT

Below code snippets explain parameter types with dependencies

***Code Snippet 1***:

```
vpc:
    cf_template: {{PROJECT_BASE}}/base/vpc/vpc_setup.template
    depends:
    params:
        vpccidr:
            value: 10.1.0.0/16
```
Here
vpc - short name of the stack

cf_template - Path for cloudfromation template. Shell environment variable can be defined in [mustache](https://mustache.github.io/) format. PROJECT_BASE is a environment variable in this example.

depends - Define dependent stack name here. It is empty because vpc stack is not depended on anything.

Params - Parameters for the stack. Template defined in the cf_template drives the parameter list here.

***Code Snippet 2:***

```
nat:
    cf_template: {{PROJECT_BASE}}/nat/nat_setup.template
    depends:
        - vpc
    params:
        natcidr:
            value: 10.1.1.0/24
        nataz:
            value: 'us-east-1a'
        vpcid:
            source: vpc
            type: resource
            variable: vpc
        privateroutetableid:
            source: vpc
            type: resource
            variable: PrivateRouteTable
...

```
In above code snippets, vpcid parameter fetches vpcid from another stack called vpc. In the vpcid parameter section

source - Source cloudformation stack. Source should be defined in "depends" section as well.
type - It can be "resource","parameter" or "output" depends on what type of resource you are referring from dependent stack. In this example, you are checking cloudformation resource called vpc which will reture physical id of vpc (vpcid)
variable - variable name defined in dependent stack
