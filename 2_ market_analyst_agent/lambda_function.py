import os
import sys
import json
from typing import Optional, Dict, Union

# Import requests that is downloaded as a part of the lambda layer
# attachment
sys.path.append("/opt/python/lib/python3.9/site-packages/")
import requests


def get_named_parameter(event, name):
    """
    Get a parameter from the lambda event
    """
    return next(item for item in event['parameters'] if item['name'] == name)['value']


def get_options_chain(ticker: str, limit: int = 10, strike_price: Optional[float] = None,
                     option_type: Optional[str] = None) -> Dict:
    """
    Get options chain data for a ticker with optional filters for strike price and option type.
    """
    api_key = os.environ.get("FINANCIAL_DATASETS_API_KEY")
    print(f"Fetched the financial dataset API key: {api_key}")
    if not api_key:
        return {"error": "Missing FINANCIAL_DATASETS_API_KEY environment variable"}

    params = {
        'ticker': ticker,
        'limit': limit
    }
    if strike_price is not None:
        params['strike_price'] = strike_price
    if option_type is not None:
        params['option_type'] = option_type
    url = 'https://api.financialdatasets.ai/options/chain'
    try:
        response = requests.get(url, headers={'X-API-Key': api_key}, params=params)
        return response.json()
    except Exception as e:
        return {"ticker": ticker, "options_chain": [], "error": str(e)}


def get_insider_trades(ticker: str, limit: int = 10) -> Dict:
    """
    Get insider trading transactions for a ticker
    """
    api_key = os.environ.get("FINANCIAL_DATASETS_API_KEY")
    print(f"Fetched the financial dataset API key: {api_key}")
    if not api_key:
        return {"error": "Missing FINANCIAL_DATASETS_API_KEY environment variable"}

    url = (
        f'https://api.financialdatasets.ai/insider-transactions'
        f'?ticker={ticker}'
        f'&limit={limit}'
    )

    try:
        response = requests.get(url, headers={'X-API-Key': api_key})
        return response.json()
    except Exception as e:
        return {"ticker": ticker, "insider_transactions": [], "error": str(e)}


def get_news(query: str, max_results: int = 5) -> Dict:
    """
    Get market news using Tavily Search API directly. In this, we use
    "google.com" as the domain to get news from Google, "bloomberg.com" to get
    news from bloomberg, etc.
    """
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return {"error": "Missing TAVILY_API_KEY environment variable"}
    
    try:
        url = "https://api.tavily.com/search"
        payload = {
            "api_key": api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": "advanced",
            "include_domains": ["google.com", "bloomberg.com"],
            "include_answer": False,
            "include_images": False,
            "include_raw_content": False
        }
        response = requests.post(url, json=payload)
        response.raise_for_status()
        results = response.json()
        return {
            "query": query,
            "results": results
        }
    except requests.exceptions.RequestException as e:
        return {"query": query, "results": [], "error": str(e)}


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

        # If the user is asking for option chain type questions, then this is the function
        # that the agent will use.
        if function == 'get_options_chain':
            ticker = get_named_parameter(event, "ticker")
            limit = int(get_named_parameter(event, "limit")) if get_named_parameter(event, "limit") else 10
            strike_price = float(get_named_parameter(event, "strike_price")) if get_named_parameter(event, "strike_price") else None
            option_type = get_named_parameter(event, "option_type") if get_named_parameter(event, "option_type") else None
            if not ticker:
                result = 'Missing required parameter: ticker'
            else:
                response = get_options_chain(ticker, limit, strike_price, option_type)
                result = response

        # If the user is asking to get insider trades on any company, then this is the function
        # that the agent calls to get data to answer the user question
        elif function == 'get_insider_trades':
            ticker = get_named_parameter(event, "ticker")
            limit = int(get_named_parameter(event, "limit")) if get_named_parameter(event, "limit") else 10
            if not ticker:
                result = 'Missing required parameter: ticker'
            else:
                response = get_insider_trades(ticker, limit)
                result = response

        # If the user is asking for market news, then this is the function
        # that the agent calls to get data to answer the user question
        elif function == 'get_news':
            query = get_named_parameter(event, "query")
            max_results = int(get_named_parameter(event, "max_results")) if get_named_parameter(event, "max_results") else 5
            if not query:
                result = 'Missing required parameter: query'
            else:
                response = get_news(query, max_results)
                result = response
        else:
            result = 'Invalid function'

        action_response = populate_function_response(event, result)
        print(f"Action response from the agent: {action_response}")
        return action_response   
    except Exception as e:
        error_result = f"Error processing request: {str(e)}"
        return populate_function_response(event, error_result)