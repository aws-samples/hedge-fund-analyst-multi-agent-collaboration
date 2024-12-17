# This file contains global variables, including names of
# the supervisor agent and the sub agents, the model ids at each 
# step, and other variables
import os
from enum import Enum
from typing import Optional, List, Dict

# This is the model that is used by the supervisor agent to
# quickly determine the sub agent to route the request to
BEDROCK_MODEL_CLAUDE_HAIKU: str = "anthropic.claude-3-haiku-20240307-v1:0"

# This is the model that is used by the sub agents to generate responses
# based on the request coming from the supervisor agent
BEDROCK_MODEL_CLAUDE_3_5_SONNET: str = "anthropic.claude-3-5-sonnet-20240620-v1:0"
BEDROCK_MODEL_LLAMA_3_2_90B: str = "us.meta.llama3-2-90b-instruct-v1:0"
BEDROCK_CLAUDE_3_SONNET: str = "anthropic.claude-3-sonnet-20240229-v1:0"
NOVA_LITE: str = "amazon.nova-lite-v1:0"
BEDROCK_NOVA_MICRO: str = "amazon.nova-micro-v1:0"

# This is the sub agent that uses the financial data API to generate
# responses on getting the balance sheets information
SUB_AGENT_NAME_TECHNICAL_ANALYST: str = "technical-analyst-agent"
SUB_AGENT_FUNDAMENTAL_ANALYST: str = "fundamental-analyst-agent"
SUB_AGENT_MARKETING_ANALYST: str = "market-analysis-agent"

# Lambda layer names
FUNDAMENTAL_LAMBDA_FUNCTION_NAME: str = 'lambda_function.py'
TECHNICAL_LAMBDA_FUNCTION_NAME: str = 'lambda_function.py'
MARKET_ANALYSIS_LAMBDA_FUNCTION_NAME: str = 'lambda_function.py'
FUNDAMENTAL_LAMBDA_LAYER: str = 'fundamental-agent-lambda-layer'