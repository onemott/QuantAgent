import requests
import os
import time

# Proxy configuration
PROXY_URL = "http://127.0.0.1:7897"
PROXIES = {
    "http": PROXY_URL,
    "https": PROXY_URL,
}

def test_connection(name, url, use_proxy=True):
    print(f"Testing connection to {name}...", end=" ", flush=True)
    try:
        start_time = time.time()
        if use_proxy:
            response = requests.get(url, proxies=PROXIES, timeout=10)
        else:
            response = requests.get(url, timeout=5)
        
        duration = time.time() - start_time
        
        if response.status_code == 200:
            print(f"SUCCESS ({duration:.2f}s)")
            return True
        else:
            print(f"FAILED (Status: {response.status_code})")
            return False
    except Exception as e:
        print(f"ERROR: {str(e)}")
        return False

if __name__ == "__main__":
    print(f"Proxy Config: {PROXY_URL}")
    print("-" * 50)
    
    # Test Binance
    # Using /api/v3/ping for a lightweight check
    test_connection("Binance (API)", "https://api.binance.com/api/v3/ping")
    
    # Test CoinGecko
    # Using /api/v3/ping
    test_connection("CoinGecko (API)", "https://api.coingecko.com/api/v3/ping")
    
    print("-" * 50)
