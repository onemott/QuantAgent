
import requests
import json

url = "http://localhost:8002/api/v1/strategy/backtest/run"
data = {
    "strategy_type": "ma",
    "symbol": "BTCUSDT",
    "interval": "1d",
    "limit": 100,
    "initial_capital": 10000
}

try:
    response = requests.post(url, json=data)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
except Exception as e:
    print(f"Error: {e}")
