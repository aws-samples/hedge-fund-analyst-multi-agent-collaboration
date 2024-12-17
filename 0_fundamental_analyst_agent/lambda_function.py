import os
import json

# Import the requests library from the lambda layer
import sys
sys.path.append("/opt/python/lib/python3.9/site-packages/")
import requests


def get_named_parameter(event, name):
    """
    Get a parameter from the lambda event
    """
    return next(item for item in event['parameters'] if item['name'] == name)['value']

def get_income_statements(ticker, period="ttm", limit=10):
    """
    Get income statements for a ticker. This is one of the functions that is used to get the 
    income statements based on the ticker specified by the user
    """
    api_key = os.environ.get("FINANCIAL_DATASETS_API_KEY")
    if not api_key:
        return {"error": "Missing FINANCIAL_DATASETS_API_KEY environment variable"}

    url = (
        f'https://api.financialdatasets.ai/financials/income-statements'
        f'?ticker={ticker}'
        f'&period={period}'
        f'&limit={limit}'
    )

    try:
        response = requests.get(url, headers={'X-API-Key': api_key})
        return response.json()
    except Exception as e:
        return {"ticker": ticker, "income_statements": [], "error": str(e)}

def get_balance_sheets(ticker, period="ttm", limit=10):
    """
    Get balance sheets for a ticker and the specified limit and time period
    """
    api_key = os.environ.get("FINANCIAL_DATASETS_API_KEY")
    print(f"Fetched the financial dataset API key: {api_key}")
    if not api_key:
        return {"error": "Missing FINANCIAL_DATASETS_API_KEY environment variable"}

    url = (
        f'https://api.financialdatasets.ai/financials/balance-sheets'
        f'?ticker={ticker}'
        f'&period={period}'
        f'&limit={limit}'
    )

    try:
        response = requests.get(url, headers={'X-API-Key': api_key})
        return response.json()
    except Exception as e:
        return {"ticker": ticker, "balance_sheets": [], "error": str(e)}

def get_cash_flow_statements(ticker, period="ttm", limit=10):
    """
    Get cash flow statements for a ticker
    """
    api_key = os.environ.get("FINANCIAL_DATASETS_API_KEY")
    print(f"Fetched the financial dataset API key: {api_key}")
    if not api_key:
        return {"error": "Missing FINANCIAL_DATASETS_API_KEY environment variable"}

    url = (
        f'https://api.financialdatasets.ai/financials/cash-flow-statements'
        f'?ticker={ticker}'
        f'&period={period}'
        f'&limit={limit}'
    )

    try:
        response = requests.get(url, headers={'X-API-Key': api_key})
        return response.json()
    except Exception as e:
        return {"ticker": ticker, "cash_flow_statements": [], "error": str(e)}

def populate_function_response(event, response_body):
    return {
        'response': {
            'actionGroup': event['actionGroup'], 
            'function': event['function'],
            'functionResponse': {
                'responseBody': {
                    'TEXT': {
                        'body': json.dumps(response_body)
                    }
                }
            }
        }
    }

def lambda_handler(event, context):
    # get the action group used during the invocation of the lambda function
    actionGroup = event.get('actionGroup', '')
    print(f"Action Group: {actionGroup}")
    # name of the function that should be invoked
    function = event.get('function', '')
    print(f"function being called: {function}")
    # parameters to invoke function with
    parameters = event.get('parameters', [])

    try:
        if function == 'get_income_statements':
            ticker = get_named_parameter(event, "ticker")
            period = get_named_parameter(event, "period")
            limit = int(get_named_parameter(event, "limit"))
            
            if not all([ticker, period, limit]):
                result = 'Missing required parameters'
            else:
                response = get_income_statements(ticker, period, limit)
                result = response

        elif function == 'get_balance_sheets':
            ticker = get_named_parameter(event, "ticker")
            period = get_named_parameter(event, "period")
            limit = int(get_named_parameter(event, "limit"))
            
            if not all([ticker, period, limit]):
                result = 'Missing required parameters'
            else:
                response = get_balance_sheets(ticker, period, limit)
                result = response

        elif function == 'get_cash_flow_statements':
            ticker = get_named_parameter(event, "ticker")
            period = get_named_parameter(event, "period")
            limit = int(get_named_parameter(event, "limit"))
            
            if not all([ticker, period, limit]):
                result = 'Missing required parameters'
            else:
                response = get_cash_flow_statements(ticker, period, limit)
                result = response

        else:
            result = 'Invalid function'

        action_response = populate_function_response(event, result)
        print(f"Action response from the agent: {action_response}")
        return action_response
    except Exception as e:
        error_result = f"Error processing request: {str(e)}"
        return populate_function_response(event, error_result)