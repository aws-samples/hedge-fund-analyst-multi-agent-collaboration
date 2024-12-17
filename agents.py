import boto3
import json
import time
import weave
import zipfile
from io import BytesIO
import logging
import pprint
import os
import subprocess
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

print(f"Boto3 version: {boto3.__version__}")

iam_client = boto3.client('iam')
sts_client = boto3.client('sts')
s3_client = boto3.client('s3')
session = boto3.session.Session()
region = session.region_name
account_id = sts_client.get_caller_identity()["Account"]
dynamodb_client = boto3.client('dynamodb')
dynamodb_resource = boto3.resource('dynamodb')
lambda_client = boto3.client('lambda')
# bedrock_agent_client = boto3.client('bedrock-agent')
bedrock_agent_client = boto3.client(
    'bedrock-agent',
    region_name=region
)

from botocore.config import Config
custom_config = Config(
            read_timeout=300,  # 5 minutes
            connect_timeout=10,  # 10 seconds
            retries={'max_attempts': 3}
        )

bedrock_agent_runtime_client = boto3.client(
    'bedrock-agent-runtime',
    region_name=region, 
    config=custom_config
)

logging.basicConfig(format='[%(asctime)s] p%(process)s {%(filename)s:%(lineno)d} %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Load .env file
load_dotenv()

# Ensure the API key is set
os.environ["WEAVE_API_KEY"] = os.getenv("WEAVE_API_KEY")

# Initialize Weave
weave.init("multi-agent-collaboration")  

def create_dynamodb(table_name, attribute_name):
    try:
        table = dynamodb_resource.create_table(
            TableName=table_name,
            KeySchema=[
                {
                    'AttributeName': attribute_name,
                    'KeyType': 'HASH'
                }
            ],
            AttributeDefinitions=[
                {
                    'AttributeName': attribute_name,
                    'AttributeType': 'S'
                }
            ],
            BillingMode='PAY_PER_REQUEST'  # Use on-demand capacity mode
        )
        # Wait for the table to be created
        print(f'Creating table {table_name}...')
        table.wait_until_exists()
        print(f'Table {table_name} created successfully!')
    except dynamodb_client.exceptions.ResourceInUseException:
        print(f'Table {table_name} already exists!')
        print('Deleting and recreating it!')
        dynamodb_client.delete_table(
            TableName=table_name
        )
        time.sleep(10)
        table = dynamodb_resource.create_table(
            TableName=table_name,
            KeySchema=[
                {
                    'AttributeName': attribute_name,
                    'KeyType': 'HASH'
                }
            ],
            AttributeDefinitions=[
                {
                    'AttributeName': attribute_name,
                    'AttributeType': 'S'
                }
            ],
            BillingMode='PAY_PER_REQUEST'  # Use on-demand capacity mode
        )
        # Wait for the table to be created
        print(f'Creating table {table_name}...')
        table.wait_until_exists()
        print(f'Table {table_name} created successfully!')


def create_lambda(
    lambda_function_name, lambda_file_path, lambda_iam_role, 
    layers=None, environment={}
):
    # Package up the lambda function code
    s = BytesIO()
    z = zipfile.ZipFile(s, 'w')
    z.write(lambda_file_path)
    z.close()
    zip_content = s.getvalue()
    try:
        # Create Lambda Function
        lambda_function = lambda_client.create_function(
            FunctionName=lambda_function_name,
            Runtime='python3.11',
            Timeout=60,
            Role=lambda_iam_role['Role']['Arn'],
            Code={'ZipFile': zip_content},
            Handler='lambda_function.lambda_handler',
            Layers=layers,
            Environment=environment
        )
    except lambda_client.exceptions.ResourceConflictException:
        print(f'{lambda_function_name} already exists, deleting it and recreating')
        lambda_client.delete_function(
            FunctionName=lambda_function_name
        )
        time.sleep(10)
        lambda_function = lambda_client.create_function(
            FunctionName=lambda_function_name,
            Runtime='python3.11',
            Timeout=60,
            Role=lambda_iam_role['Role']['Arn'],
            Code={'ZipFile': zip_content},
            Handler='lambda_function.lambda_handler',
            Layers=layers,
            Environment=environment
        )
    return lambda_function


def create_lambda_role(agent_name):
    lambda_function_role = f'{agent_name}-lambda-role'
    lambda_basic_role = 'arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole'
    dynamodb_role = 'arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess'
    assume_role_policy_document = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Service": "lambda.amazonaws.com"
                },
                "Action": "sts:AssumeRole"
            }
        ]
    }

    assume_role_policy_document_json = json.dumps(
        assume_role_policy_document
    )
    # Create IAM Role for the Lambda function
    try:
        lambda_iam_role = iam_client.create_role(
            RoleName=lambda_function_role,
            AssumeRolePolicyDocument=assume_role_policy_document_json
        )

        # Pause to make sure role is created
        time.sleep(10)
    except iam_client.exceptions.EntityAlreadyExistsException:
        print("Role already exists -- deleting and creating it again")
        policies = iam_client.list_attached_role_policies(
            RoleName=lambda_function_role,
            MaxItems=100
        )
        for policy in policies['AttachedPolicies']:
            print(f"Detaching {policy['PolicyName']}")
            iam_client.detach_role_policy(
                RoleName=lambda_function_role,
                PolicyArn=policy['PolicyArn']
            )
        print(f"deleting {lambda_function_role}")
        iam_client.delete_role(
            RoleName=lambda_function_role
        )
        print(f"recreating {lambda_function_role}")
        lambda_iam_role = iam_client.create_role(
            RoleName=lambda_function_role,
            AssumeRolePolicyDocument=assume_role_policy_document_json
        )

    # Attach the AWSLambdaBasicExecutionRole policy
    print(f"attaching basic lambda permissions to {lambda_function_role}")
    iam_client.attach_role_policy(
        RoleName=lambda_function_role,
        PolicyArn=lambda_basic_role
    )
    print(f"attaching dynamodb permissions to {lambda_function_role}")
    iam_client.attach_role_policy(
        RoleName=lambda_function_role,
        PolicyArn=dynamodb_role
    )

    return lambda_iam_role


def wait_agent_status_update(agent_id):
    response = bedrock_agent_client.get_agent(agentId=agent_id)
    agent_status = response['agent']['agentStatus']
    while agent_status.endswith('ING'):
        print(f'Waiting for agent status to change. Current status {agent_status}')
        time.sleep(5)
        try:
            response = bedrock_agent_client.get_agent(agentId=agent_id)
            agent_status = response['agent']['agentStatus']
        except bedrock_agent_client.exceptions.ResourceNotFoundException:
            agent_status = 'DELETED'
    print(f'Agent id {agent_id} current status: {agent_status}')


def create_agent_object(
    agent_name, agent_role, agent_description,
    idle_session_ttl_in_seconds, agent_foundation_model,
    agent_instruction, agent_collaboration, prompt_override_configuration
):
    try:
        if prompt_override_configuration is not None:
            response = bedrock_agent_client.create_agent(
                agentName=agent_name,
                agentResourceRoleArn=agent_role['Role']['Arn'],
                description=agent_description,
                idleSessionTTLInSeconds=idle_session_ttl_in_seconds,
                foundationModel=agent_foundation_model,
                instruction=agent_instruction,
                agentCollaboration=agent_collaboration,
                promptOverrideConfiguration=prompt_override_configuration
            )
        else:
            response = bedrock_agent_client.create_agent(
                agentName=agent_name,
                agentResourceRoleArn=agent_role['Role']['Arn'],
                description=agent_description,
                idleSessionTTLInSeconds=idle_session_ttl_in_seconds,
                foundationModel=agent_foundation_model,
                instruction=agent_instruction,
                agentCollaboration=agent_collaboration
            )
        agent_id = response['agent']['agentId']
        return agent_id
    except bedrock_agent_client.exceptions.ConflictException:
        agents = bedrock_agent_client.list_agents(
            maxResults=1000
        )
        agent_id = None
        for agent in agents['agentSummaries']:
            if agent['agentName'] == agent_name:
                agent_id = agent['agentId']
        agent_aliases = bedrock_agent_client.list_agent_aliases(
            agentId=agent_id,
            maxResults=100
        )
        for alias in agent_aliases['agentAliasSummaries']:
            alias_id = alias['agentAliasId']
            print(f'Deleting alias {alias_id} from agent {agent_id}')
            response = bedrock_agent_client.delete_agent_alias(
                agentAliasId=alias_id,
                agentId=agent_id
            )
        bedrock_agent_client.delete_agent(
            agentId=agent_id
        )
        wait_agent_status_update(agent_id)
        if prompt_override_configuration is not None:
            response = bedrock_agent_client.create_agent(
                agentName=agent_name,
                agentResourceRoleArn=agent_role['Role']['Arn'],
                description=agent_description,
                idleSessionTTLInSeconds=idle_session_ttl_in_seconds,
                foundationModel=agent_foundation_model,
                instruction=agent_instruction,
                agentCollaboration=agent_collaboration,
                promptOverrideConfiguration=prompt_override_configuration
            )
        else:
            response = bedrock_agent_client.create_agent(
                agentName=agent_name,
                agentResourceRoleArn=agent_role['Role']['Arn'],
                description=agent_description,
                idleSessionTTLInSeconds=idle_session_ttl_in_seconds,
                foundationModel=agent_foundation_model,
                instruction=agent_instruction,
                agentCollaboration=agent_collaboration
            )
        agent_id = response['agent']['agentId']
        return agent_id


def create_agent(
    agent_name, agent_instruction,
    agent_foundation_model="anthropic.claude-3-sonnet-20240229-v1:0",
    idle_session_ttl_in_seconds=1800,
    agent_description="",
    action_group_config=None,
    kb_config=None,
    agent_collaboration='DISABLED',
    prompt_override_configuration=None,
    create_alias=True
):
    print('creating agent')
    kb_id = None
    if kb_config:
        kb_id = kb_config['kb_id']
    if agent_collaboration in ['SUPERVISOR', 'SUPERVISOR_ROUTER']:
        supervisor_agent = True
    else:
        supervisor_agent = False
    if action_group_config and 'api_schema' in action_group_config:
        bucket_name = action_group_config['api_schema']['bucket_name']
        bucket_key = action_group_config['api_schema']['bucket_key']
        schema_arn = f'arn:aws:s3:::{bucket_name}/{bucket_key}'
    else:
        schema_arn = None
    agent_role = create_agent_role_and_policies(
        agent_name, agent_foundation_model, kb_id=kb_id,
        supervisor_agent=supervisor_agent, schema_arn=schema_arn
    )
    agent_id = create_agent_object(
        agent_name, agent_role, agent_description,
        idle_session_ttl_in_seconds, agent_foundation_model,
        agent_instruction, agent_collaboration, prompt_override_configuration
    )
    # if action group configuration is provided
    if action_group_config:
        print('creating and attaching action group')
        lambda_iam_role = create_lambda_role(agent_name)
        layers = []
        environment = {}
        if 'lambda_layers' in action_group_config:
            layers = action_group_config['lambda_layers']
        if 'environment' in action_group_config:
            environment = action_group_config['environment']
        lambda_function = create_lambda(
            action_group_config['lambda_function_name'],
            action_group_config['lambda_file_path'],
            lambda_iam_role,
            layers,
            environment
        )
        if 'functions' in action_group_config:
            agent_functions = action_group_config['functions']
            bedrock_agent_client.create_agent_action_group(
                agentId=agent_id,
                agentVersion='DRAFT',
                actionGroupExecutor={
                    'lambda': lambda_function['FunctionArn']
                },
                actionGroupName=action_group_config['name'],
                functionSchema={
                    'functions': agent_functions
                },
                description=action_group_config['description']
            )
        elif 'api_schema' in action_group_config:
            api_schema = action_group_config['api_schema']
            bedrock_agent_client.create_agent_action_group(
                agentId=agent_id,
                agentVersion='DRAFT',
                actionGroupExecutor={
                    'lambda': lambda_function['FunctionArn']
                },
                actionGroupName=action_group_config['name'],
                apiSchema={
                    's3': {
                        's3BucketName': api_schema['bucket_name'],
                        's3ObjectKey': api_schema['bucket_key']
                    }
                },
                description=action_group_config['description']
            )
        else:
            raise ("functions or api_schema must be provided in action_group_config")
        lambda_client.add_permission(
            FunctionName=action_group_config['lambda_function_name'],
            StatementId='allow_bedrock_prod',
            Action='lambda:InvokeFunction',
            Principal='bedrock.amazonaws.com',
            SourceArn=f"arn:aws:bedrock:{region}:{account_id}:agent/{agent_id}"
        )
    if kb_config:
        print('associating knowledge base')
        bedrock_agent_client.associate_agent_knowledge_base(
            agentId=agent_id,
            agentVersion='DRAFT',
            description=kb_config['kb_instruction'],
            knowledgeBaseId=kb_config['kb_id'],
            knowledgeBaseState='ENABLED'
        )


    if create_alias:
        wait_agent_status_update(agent_id)
        bedrock_agent_client.prepare_agent(
            agentId=agent_id
        )
        wait_agent_status_update(agent_id)
        agent_alias = bedrock_agent_client.create_agent_alias(
            agentAliasName='v1', agentId=agent_id
        )
        agent_alias_id = agent_alias['agentAlias']['agentAliasId']
        agent_alias_arn = agent_alias['agentAlias']['agentAliasArn']
        wait_agent_status_update(agent_id)
    else:
        agent_alias_id = 'TSTALIASID'
        agent_alias_arn = None
    return agent_id, agent_alias_id, agent_alias_arn


def associate_sub_agents(
    supervisor_agent_id, 
    sub_agents_list
):
    for sub_agent in sub_agents_list:
        wait_agent_status_update(supervisor_agent_id)
        association_response = bedrock_agent_client.associate_agent_collaborator(
            agentId=supervisor_agent_id,
            agentVersion='DRAFT',
            agentDescriptor={
                'aliasArn': sub_agent['sub_agent_alias_arn']
            },
            collaboratorName=sub_agent['sub_agent_association_name'],
            collaborationInstruction=sub_agent['sub_agent_instruction'],
            relayConversationHistory=sub_agent['relay_conversation_history']
        )
        wait_agent_status_update(supervisor_agent_id)
        bedrock_agent_client.prepare_agent(
            agentId=supervisor_agent_id
        )
        wait_agent_status_update(supervisor_agent_id)
    supervisor_agent_alias = bedrock_agent_client.create_agent_alias(
        agentAliasName='multi-agent', 
        agentId=supervisor_agent_id
    )
    supervisor_agent_alias_id = supervisor_agent_alias['agentAlias']['agentAliasId']
    supervisor_agent_alias_arn = supervisor_agent_alias['agentAlias']['agentAliasArn']
    return supervisor_agent_alias_id, supervisor_agent_alias_arn


def list_agent_collaborators(agent_id):
    associations = bedrock_agent_client.list_agent_collaborators(
        agentId=agent_id, 
        agentVersion='DRAFT'
    )
    return associations


def create_agent_role_and_policies(
    agent_name, agent_foundation_model, schema_arn=None,
    kb_id=None, supervisor_agent=False
):
    agent_bedrock_allow_policy_name = f"{agent_name}-ba"
    agent_role_name = f'AmazonBedrockExecutionRoleForAgents_{agent_name}'
    # Create IAM policies for agent
    statements = [
        {
            "Sid": "AmazonBedrockAgentBedrockFoundationModelPolicy",
            "Effect": "Allow",
            "Action": "bedrock:InvokeModel",
            "Resource": [
                f"arn:aws:bedrock:{region}::foundation-model/{agent_foundation_model}"
            ]
        }
    ]
    if schema_arn:
        statements.append(
            {
                "Sid": "AllowAgentAccessOpenAPISchema",
                "Effect": "Allow",
                "Action": [
                    "s3:GetObject"
                ],
                "Resource": [
                    schema_arn
                ]
            }
        )
    if supervisor_agent:
        statements.append(
            {
                "Sid": "SupervisorAgentPolicy",
                "Effect": "Allow",
                "Action": [
                    "bedrock:GetAgentAlias",
                    "bedrock:InvokeAgent"
                ],
                "Resource": [
                    "arn:aws:bedrock:*:*:agent/*",
                    "arn:aws:bedrock:*:*:agent-alias/*",
                ]
            }
        )
    # add Knowledge Base retrieve and retrieve and generate permissions if agent has KB attached to it
    if kb_id:
        statements.append(
            {
                "Sid": "QueryKB",
                "Effect": "Allow",
                "Action": [
                    "bedrock:Retrieve",
                    "bedrock:RetrieveAndGenerate"
                ],
                "Resource": [
                    f"arn:aws:bedrock:{region}:{account_id}:knowledge-base/{kb_id}"
                ]
            }
        )

    bedrock_agent_bedrock_allow_policy_statement = {
        "Version": "2012-10-17",
        "Statement": statements
    }

    bedrock_policy_json = json.dumps(bedrock_agent_bedrock_allow_policy_statement)
    try:
        agent_bedrock_policy = iam_client.create_policy(
            PolicyName=agent_bedrock_allow_policy_name,
            PolicyDocument=bedrock_policy_json
        )
    except iam_client.exceptions.EntityAlreadyExistsException:
        print(f'Policy {agent_bedrock_allow_policy_name} already exists')
        print(f'Checking if {agent_role_name} role also exists')
        response = iam_client.list_roles(
            MaxItems=1000
        )
        exists = False
        for role in response['Roles']:
            if role['RoleName'] == agent_role_name:
                exists = True
        if exists:
            policies = iam_client.list_attached_role_policies(
                RoleName=agent_role_name,
                MaxItems=1000
            )
            for policy in policies['AttachedPolicies']:
                print(f"Detaching and deleting {policy['PolicyName']}")
                iam_client.detach_role_policy(
                    RoleName=agent_role_name,
                    PolicyArn=policy['PolicyArn']
                )
                iam_client.delete_policy(
                    PolicyArn=policy['PolicyArn']
                )
            print(f"deleting {agent_role_name}")
            iam_client.delete_role(
                RoleName=agent_role_name
            )
        print(f'Recreating {agent_bedrock_allow_policy_name}')
        agent_bedrock_policy = iam_client.create_policy(
            PolicyName=agent_bedrock_allow_policy_name,
            PolicyDocument=bedrock_policy_json
        )
    # Create IAM Role for the agent and attach IAM policies
    assume_role_policy_document = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "",
                "Effect": "Allow",
                "Principal": {
                    "Service": "preprod.bedrock.aws.internal"
                },
                "Action": "sts:AssumeRole"
            },
            {
                "Sid": "",
                "Effect": "Allow",
                "Principal": {
                    "Service": "beta.bedrock.aws.internal"
                },
                "Action": "sts:AssumeRole"
            },
            {
              "Effect": "Allow",
              "Principal": {
                "Service": "bedrock.amazonaws.com"
              },
              "Action": "sts:AssumeRole"
            }
        ]
    }

    assume_role_policy_document_json = json.dumps(assume_role_policy_document)
    agent_role = iam_client.create_role(
        RoleName=agent_role_name,
        AssumeRolePolicyDocument=assume_role_policy_document_json
    )

    # Pause to make sure role is created
    time.sleep(10)

    iam_client.attach_role_policy(
        RoleName=agent_role_name,
        PolicyArn=agent_bedrock_policy['Policy']['Arn']
    )
    return agent_role


def delete_agent_roles_and_policies(agent_name):
    agent_bedrock_allow_policy_name = f"{agent_name}-ba"
    agent_role_name = f'AmazonBedrockExecutionRoleForAgents_{agent_name}'
    dynamodb_access_policy_name = f'{agent_name}-dynamodb-policy'
    lambda_function_role = f'{agent_name}-lambda-role'

    for policy in [agent_bedrock_allow_policy_name]:
        try:
            iam_client.detach_role_policy(
                RoleName=agent_role_name,
                PolicyArn=f'arn:aws:iam::{account_id}:policy/{policy}'
            )
        except Exception as e:
            print(f"Could not detach {policy} from {agent_role_name}")
            print(e)

    for policy in [dynamodb_access_policy_name]:
        try:
            iam_client.detach_role_policy(
                RoleName=lambda_function_role,
                PolicyArn=f'arn:aws:iam::{account_id}:policy/{policy}'
            )
        except Exception as e:
            print(f"Could not detach {policy} from {lambda_function_role}")
            print(e)

    try:
        iam_client.detach_role_policy(
            RoleName=lambda_function_role,
            PolicyArn='arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole'
        )
    except Exception as e:
        print(f"Could not detach AWSLambdaBasicExecutionRole from {lambda_function_role}")
        print(e)

    for role_name in [agent_role_name, lambda_function_role]:
        try:
            iam_client.delete_role(
                RoleName=role_name
            )
        except Exception as e:
            print(f"Could not delete role {role_name}")
            print(e)

    for policy in [agent_bedrock_allow_policy_name, dynamodb_access_policy_name]:
        try:
            iam_client.delete_policy(
                PolicyArn=f'arn:aws:iam::{account_id}:policy/{policy}'
            )
        except Exception as e:
            print(f"Could not delete policy {policy}")
            print(e)


def clean_up_resources(
    table_name, lambda_function, lambda_function_name,
    agent_action_group_response, agent_functions,
    agent_id, kb_id, alias_id
):
    action_group_id = agent_action_group_response['agentActionGroup']['actionGroupId']
    action_group_name = agent_action_group_response['agentActionGroup']['actionGroupName']
    # Delete Agent Action Group, Agent Alias, and Agent
    try:
        bedrock_agent_client.update_agent_action_group(
            agentId=agent_id,
            agentVersion='DRAFT',
            actionGroupId=action_group_id,
            actionGroupName=action_group_name,
            actionGroupExecutor={
                'lambda': lambda_function['FunctionArn']
            },
            functionSchema={
                'functions': agent_functions
            },
            actionGroupState='DISABLED',
        )
        bedrock_agent_client.disassociate_agent_knowledge_base(
            agentId=agent_id,
            agentVersion='DRAFT',
            knowledgeBaseId=kb_id
        )
        bedrock_agent_client.delete_agent_action_group(
            agentId=agent_id,
            agentVersion='DRAFT',
            actionGroupId=action_group_id
        )
        bedrock_agent_client.delete_agent(agentId=agent_id)
        print(
            f"Agent {agent_id}, Agent Alias {alias_id}, and Action Group have been deleted."
        )
    except Exception as e:
        print(f"Error deleting Agent resources: {e}")

    # Delete Lambda function
    try:
        lambda_client.delete_function(FunctionName=lambda_function_name)
        print(f"Lambda function {lambda_function_name} has been deleted.")
    except Exception as e:
        print(f"Error deleting Lambda function {lambda_function_name}: {e}")

    # Delete DynamoDB table
    try:
        dynamodb_client.delete_table(TableName=table_name)
        print(f"Table {table_name} is being deleted...")
        waiter = dynamodb_client.get_waiter('table_not_exists')
        waiter.wait(TableName=table_name)
        print(f"Table {table_name} has been deleted.")
    except Exception as e:
        print(f"Error deleting table {table_name}: {e}")

def agent_call_display_name(call):
    query_preview = call.inputs['query'][:30] + '...' if len(call.inputs['query']) > 30 else call.inputs['query']
    agent_id = call.inputs['agent_id']
    return f"Agent_{agent_id}__{query_preview}"

@weave.op(call_display_name=agent_call_display_name)
def invoke_agent_helper(
    query, session_id, agent_id, alias_id, enable_trace=False, session_state=None, trace_level="core"
):
    """
    Invokes the agent and optionally prints detailed trace information.
    trace_level can be "core" or "all".
    """
    with weave.attributes({
        "session_id": session_id,
        "agent_id": agent_id,
        "alias_id": alias_id,
        "enable_trace": enable_trace
    }):
        end_session: bool = False
        if not session_state:
            session_state = {}
        # invoke the agent API
        agent_response = bedrock_agent_runtime_client.invoke_agent(
            inputText=query,
            agentId=agent_id,
            agentAliasId=alias_id,
            sessionId=session_id,
            enableTrace=enable_trace,
            endSession=end_session,
            sessionState=session_state
        )

        # If tracing is enabled, log a summary of the agent_response metadata
        if enable_trace:
            logger.info("invoke_agent response metadata:")
            logger.info(json.dumps(agent_response['ResponseMetadata'], indent=2))

        event_stream = agent_response['completion']
        try:
            for event in event_stream:
                if 'chunk' in event:
                    data = event['chunk']['bytes']
                    agent_answer = data.decode('utf8')
                    if enable_trace:
                        logger.info("==== Final Answer Chunk Received ====")
                        logger.info(agent_answer)
                        # If there are other keys in event['chunk'], log them as well
                        for key in event['chunk']:
                            if key != 'bytes':
                                logger.info(f"Chunk {key}: {json.dumps(event['chunk'][key], indent=3)}")
                    return agent_answer

                elif 'trace' in event:
                    if enable_trace:
                        # If trace_level is "all", print the entire trace object
                        if trace_level == "all":
                            logger.info("==== Full Trace Event ====")
                            logger.info(json.dumps(event['trace'], indent=2))
                        else:
                            # "core" trace: Print just a summary
                            trace_obj = event['trace']
                            logger.info("==== Trace Event Received ====")
                            # Print callerChain info
                            if 'callerChain' in trace_obj:
                                logger.info(f"callerChain: {json.dumps(trace_obj['callerChain'], indent=2)}")

                            # Print routingClassifierTrace summary if present
                            if 'trace' in trace_obj and 'routingClassifierTrace' in trace_obj['trace']:
                                routing_trace = trace_obj['trace']['routingClassifierTrace']
                                logger.info("Routing Classifier Trace Detected")
                                if 'modelInvocationOutput' in routing_trace:
                                    raw_resp_str = routing_trace['modelInvocationOutput']['rawResponse']['content']
                                    logger.info(f"Routing Model Raw Response: {raw_resp_str}")

                            # Print orchestrationTrace summary if present
                            if 'trace' in trace_obj and 'orchestrationTrace' in trace_obj['trace']:
                                orch_trace = trace_obj['trace']['orchestrationTrace']
                                logger.info("Orchestration Trace Detected")
                                # You can add more detailed logging here as needed
                                if 'rationale' in orch_trace:
                                    logger.info(f"Agent Rationale: {orch_trace['rationale']['text']}")
                                if 'observation' in orch_trace:
                                    logger.info(f"Agent Observation: {json.dumps(orch_trace['observation'], indent=2)}")

                else:
                    # Unexpected event type
                    raise Exception("unexpected event.", event)
        except Exception as e:
            raise Exception("unexpected event.", e)


def create_lambda_layer(agent_name, requirements):
    # Create directory structure
    Path("layer/python").mkdir(parents=True, exist_ok=True)

    # Install packages
    subprocess.check_call([
        "pip",
        "install",
        "-r",
        requirements,
        "-t",
        "layer/python"
    ])

    # Install zip
    subprocess.check_call([
        "sudo",
        "apt",
        "install",
        "zip"
    ])

    # Create ZIP file
    subprocess.check_call([
        "zip",
        "-r",
        "layer.zip",
        "python"
    ], cwd="layer")

    # Create Lambda layer
    lambda_client = boto3.client('lambda')

    try:
        with open("layer/layer.zip", 'rb') as zip_file:
            response = lambda_client.publish_layer_version(
                LayerName=f'{agent_name}-layer',
                Description='Action group lambda layer',
                Content={
                    'ZipFile': zip_file.read()
                },
                CompatibleRuntimes=[
                    'python3.7', 'python3.8', 'python3.9', 'python3.10', 'python3.11', 'python3.12'
                ],
                CompatibleArchitectures=['x86_64']
            )

        print(f"Layer created successfully. Version: {response['Version']}")
        print(f"Layer ARN: {response['LayerVersionArn']}")

        # Clean up
        os.system("rm -rf layer")

        return response['LayerVersionArn']

    except Exception as e:
        print(f"Error creating layer: {str(e)}")
        return None


def upload_api_schema(agent_name, api_schema_path):
    bucket_name = f'{agent_name}-{account_id}-{region}'
    # Create S3 bucket for Open API schema
    if region == "us-east-1":
        s3_client.create_bucket(
            Bucket=bucket_name
        )
    else:
        s3_client.create_bucket(
            Bucket=bucket_name,
            CreateBucketConfiguration={
                'LocationConstraint': region
            }
        )
    print(bucket_name)
    # Upload Open API schema to this s3 bucket
    s3_client.upload_file(api_schema_path, bucket_name, api_schema_path)
    return bucket_name, api_schema_path
