from setuptools import setup, find_packages

setup(
    name='cfnstack-aws',
    version='0.3',
    packages=find_packages(),
    url='',
    license='MDL',
    author='Vijayakumar Jawaharlal',
    author_email='vijay_jawaharial@external.mckinsey.com',
    description='Manage and Modularize cloudformation templates',
    install_requires=['PyYAML','argparse','boto3','botocore','simplejson','pystache'],
    include_package_data=True,
    entry_points={
        'console_scripts': [
            'cfnstack=cfnstack:main',
        ],
    },
)
