import sys
import os
import pandas as pd
import numpy as np
import time

# Add backend to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from app.services.backtester.vectorized import VectorizedBacktester
from app.services.backtester.event_driven import EventDrivenBacktester
from app.services.strategy_templates import build_signal_func

def generate_dummy_data(n=1000):
    dates = pd.date_range(start='2023-01-01', periods=n, freq='1h')
    close = np.random.normal(100, 1, n).cumsum() + 1000
    df = pd.DataFrame({'close': close}, index=dates)
    return df

def test_backtesters():
    print("Generating dummy data...")
    df = generate_dummy_data(5000)
    
    # Use a simple MA strategy
    params = {"fast_period": 10, "slow_period": 30}
    signal_func = build_signal_func("ma", params)
    
    print("\n--- Testing VectorizedBacktester ---")
    start = time.time()
    vb = VectorizedBacktester(df, signal_func)
    res_v = vb.run()
    end = time.time()
    print(f"Vectorized Time: {end - start:.6f}s")
    print(f"Sharpe: {res_v['sharpe_ratio']:.4f}, Return: {res_v['total_return']:.2f}%")
    
    print("\n--- Testing EventDrivenBacktester (Numba) ---")
    start = time.time()
    eb = EventDrivenBacktester(df, signal_func)
    res_e = eb.run() # First run compiles
    end = time.time()
    print(f"Numba First Run (Compile): {end - start:.6f}s")
    print(f"Sharpe: {res_e['sharpe_ratio']:.4f}, Return: {res_e['total_return']:.2f}%")
    
    start = time.time()
    res_e2 = eb.run() # Second run cached
    end = time.time()
    print(f"Numba Second Run: {end - start:.6f}s")
    
    # Compare results
    print("\n--- Comparison ---")
    print(f"Vectorized Sharpe: {res_v['sharpe_ratio']:.4f}")
    print(f"Numba Sharpe:      {res_e['sharpe_ratio']:.4f}")
    
    diff = abs(res_v['sharpe_ratio'] - res_e['sharpe_ratio'])
    if diff < 0.1:
        print("✅ Results match closely.")
    else:
        print("⚠️ Results differ significantly (expected due to logic differences like fill price).")

if __name__ == "__main__":
    test_backtesters()
