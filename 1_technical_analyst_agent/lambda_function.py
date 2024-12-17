import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Union, Dict

# Import the requests library from the lambda layer
import sys
sys.path.append("/opt/python/lib/python3.9/site-packages/")

# Import the libraries that are attached to the lambda via the lambda
# layer: ta, requests, pandas
import requests
# Default time period
DEFAULT_PERIOD: int = 14 

# Set a logger
logging.basicConfig(format='[%(asctime)s] p%(process)s {%(filename)s:%(lineno)d} %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


def get_named_parameter(event, name):
    """
    Get a parameter from the lambda event
    """
    return next(item for item in event['parameters'] if item['name'] == name)['value']


def get_stock_prices(ticker: str, start_date: str, end_date: str, limit: int = 5000) -> Union[Dict, str]:
    api_key = os.environ.get("FINANCIAL_DATASETS_API_KEY")
    logger.info(f"API Key present: {'yes' if api_key else 'no'}")
    if not api_key:
        logger.error("Missing FINANCIAL_DATASETS_API_KEY environment variable")
        return {"error": "Missing FINANCIAL_DATASETS_API_KEY environment variable"}
    url = (
        f"https://api.financialdatasets.ai/prices"
        f"?ticker={ticker}"
        f"&start_date={start_date}"
        f"&end_date={end_date}"
        f"&interval=day"
        f"&interval_multiplier=1"
        f"&limit={limit}"
    )
    try:
        logger.info(f"Making API request to: {url}")
        response = requests.get(url, headers={'X-API-Key': api_key})
        logger.info(f"API response status code: {response.status_code}")
        if response.status_code != 200:
            logger.error(f"API error: {response.text}")
            return {"error": f"API returned status code {response.status_code}"}
        return response.json()
    except Exception as e:
        logger.error(f"Error in get_stock_prices: {str(e)}", exc_info=True)
        return {"ticker": ticker, "prices": [], "error": str(e)}


def get_current_stock_price(ticker: str) -> Union[Dict, str]:
    """
    Get current stock price based on the ticker provided by the user
    """
    api_key = os.environ.get("FINANCIAL_DATASETS_API_KEY")
    if not api_key:
        return {"error": "Missing FINANCIAL_DATASETS_API_KEY environment variable"}

    url = f"https://api.financialdatasets.ai/prices/snapshot?ticker={ticker}"

    try:
        response = requests.get(url, headers={'X-API-Key': api_key})
        return response.json()
    except Exception as e:
        return {"ticker": ticker, "price": None, "error": str(e)}


def get_technical_indicators(ticker: str, indicator: str, period: int = 14,
                           start_date: Optional[str] = None, end_date: Optional[str] = None) -> Union[Dict, str]:
    """
    This function calculates technical indicators based on the provided parameters.
    It supports the following indicators: SMA, EMA, and RSI.
    """
    try:
        adjusted_start = (datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=period * 2)).strftime("%Y-%m-%d")
        
        price_data = get_stock_prices(
            ticker=ticker,
            start_date=adjusted_start,
            end_date=end_date,
            limit=5000
        )

        if "error" in price_data:
            return price_data

        # Convert price data to list of dictionaries with proper datetime
        prices = price_data["prices"]
        for price in prices:
            price['time'] = price['time'].split(' EDT')[0].split(' EST')[0]
            price['time'] = datetime.strptime(price['time'], "%Y-%m-%d %H:%M:%S")

        # Filter date range
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        prices = [p for p in prices if start_dt <= p['time'] <= end_dt]

        result = {
            "ticker": ticker,
            "indicator": indicator,
            "period": period,
            "data": []
        }

        if indicator.lower() == "sma":
            for i in range(len(prices)):
                if i >= period - 1:
                    sum_prices = sum(p['close'] for p in prices[i-period+1:i+1])
                    sma = sum_prices / period
                    result["data"].append({
                        "time": prices[i]['time'].strftime("%Y-%m-%d %H:%M:%S"),
                        "time_milliseconds": int(prices[i]['time'].timestamp() * 1000),
                        "value": float(sma)
                    })
        
        elif indicator.lower() == "ema":
            multiplier = 2 / (period + 1)
            ema = prices[0]['close']
            for i in range(len(prices)):
                ema = (prices[i]['close'] - ema) * multiplier + ema
                result["data"].append({
                    "time": prices[i]['time'].strftime("%Y-%m-%d %H:%M:%S"),
                    "time_milliseconds": int(prices[i]['time'].timestamp() * 1000),
                    "value": float(ema)
                })

        elif indicator.lower() == "rsi":
            changes = []
            for i in range(1, len(prices)):
                changes.append(prices[i]['close'] - prices[i-1]['close'])

            for i in range(len(changes) - period + 1):
                gains = sum(max(change, 0) for change in changes[i:i+period])
                losses = sum(abs(min(change, 0)) for change in changes[i:i+period])
                
                avg_gain = gains / period
                avg_loss = losses / period
                
                if avg_loss == 0:
                    rsi = 100
                else:
                    rs = avg_gain / avg_loss
                    rsi = 100 - (100 / (1 + rs))
                
                result["data"].append({
                    "time": prices[i+period]['time'].strftime("%Y-%m-%d %H:%M:%S"),
                    "time_milliseconds": int(prices[i+period]['time'].timestamp() * 1000),
                    "value": float(rsi)
                })
        return result
    except Exception as e:
        logger.error(f"Error in get_technical_indicators: {str(e)}")
        raise e


def populate_function_response(event, response_body):
    return {
        'response': {
            'actionGroup': event['actionGroup'],
            'function': event['function'],
            'functionResponse': {
                'responseBody': response_body
            }
        }
    }


def lambda_handler(event, context):
    logger.info(f"Received event: {json.dumps(event)}")  # Log the incoming event
    function = event.get('function', '')
    logger.info(f"Processing function: {function}")  # Log which function is being called
    
    try:
        response = {}
        
        # If the user is asking for the current stock price, then identify the ticker, 
        # and return the latest stock price
        if function == 'get_current_stock_price':
            logger.info("Executing get_current_stock_price")
            ticker = get_named_parameter(event, "ticker")
            logger.info(f"Ticker: {ticker}")
            response = get_current_stock_price(ticker)
            logger.info(f"Response: {json.dumps(response)}")
        
        # if the user is asking for data on the stock price for a ticker for a time period then
        # this is the function that the agent calls
        elif function == 'get_stock_prices':
            logger.info("Executing get_stock_prices")
            ticker = get_named_parameter(event, "ticker")
            start_date = get_named_parameter(event, "start_date")
            end_date = get_named_parameter(event, "end_date")
            limit = int(get_named_parameter(event, "limit"))
            logger.info(f"Parameters: ticker={ticker}, start_date={start_date}, end_date={end_date}, limit={limit}")
            
            response = get_stock_prices(
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
                limit=limit
            )
            logger.info(f"Response: {json.dumps(response)}")
            
        # If the user is looking to get technical indicators on the stock, for example the SMA, etc
        # then this is the function that the agent calls
        elif function == 'get_technical_indicators':
            logger.info("Executing get_technical_indicators")
            ticker = get_named_parameter(event, "ticker")
            indicator = get_named_parameter(event, "indicator")
            start_date = get_named_parameter(event, "start_date")
            end_date = get_named_parameter(event, "end_date")
            period = int(get_named_parameter(event, "period")) if "period" in [p["name"] for p in event["parameters"]] else DEFAULT_PERIOD
            
            response = get_technical_indicators(
                ticker=ticker,
                indicator=indicator,
                period=period,
                start_date=start_date,
                end_date=end_date
            )
            logger.info(f"Response: {json.dumps(response)}")
            
        else:
            logger.warning(f"Invalid function: {function}")
            response = {
                "error": "Invalid function",
                "message": f"Function {function} is not supported"
            }
            
        final_response = populate_function_response(event, response)
        logger.info(f"Final response: {json.dumps(final_response)}")
        return final_response
        
    except Exception as e:
        logger.error(f"Error in lambda_handler: {str(e)}", exc_info=True)
        error_response = {
            "error": str(e),
            "message": f"Failed to execute {function}"
        }
        return populate_function_response(event, error_response)