import asyncio
import pandas as pd
import numpy as np
from app.services.indicators import donchian_channels, ichimoku_cloud
from app.services.strategy_templates import build_signal_func
from app.services.risk_manager import risk_manager
from app.services.macro_analysis_service import macro_analysis_service

async def test_new_modules():
    print("=== Testing New Indicators ===")
    # Create dummy data
    data = {
        "high": np.random.uniform(100, 110, 100),
        "low": np.random.uniform(90, 100, 100),
        "close": np.random.uniform(95, 105, 100),
        "open": np.random.uniform(95, 105, 100),
        "volume": np.random.uniform(1000, 5000, 100)
    }
    df = pd.DataFrame(data)
    
    # Test Donchian
    df_donchian = donchian_channels(df, period=20)
    print(f"Donchian Channels columns: {df_donchian.columns.tolist()}")
    assert "donchian_upper" in df_donchian.columns
    
    # Test Ichimoku
    df_ichi = ichimoku_cloud(df)
    print(f"Ichimoku Cloud columns: {df_ichi.columns.tolist()}")
    assert "ichi_span_a" in df_ichi.columns
    
    print("\n=== Testing Strategy Templates ===")
    # Test Turtle Strategy
    turtle_func = build_signal_func("turtle", {"entry_period": 20, "exit_period": 10})
    signals_turtle = turtle_func(df)
    print(f"Turtle Signals (first 5): {signals_turtle.head().tolist()}")
    
    # Test Ichimoku Strategy
    ichi_func = build_signal_func("ichimoku", {"tenkan_period": 9, "kijun_period": 26})
    signals_ichi = ichi_func(df)
    print(f"Ichimoku Signals (first 5): {signals_ichi.head().tolist()}")
    
    print("\n=== Testing Anti-Black Swan Risk Logic ===")
    # Test Risk Check with simulated volatility spike
    # We'll call check_order multiple times to see if tail risk triggers
    triggers = 0
    for _ in range(20):
        res = await risk_manager.check_order(
            symbol="BTCUSDT",
            side="BUY",
            quantity=1.0,
            price=50000.0,
            current_balance=100000.0,
            current_positions={},
            total_portfolio_value=100000.0,
            market_price=50000.0
        )
        if not res.allowed and res.rule == "TAIL_RISK_HALT":
            triggers += 1
    print(f"Tail Risk Triggered {triggers} times out of 20 checks.")

    print("\n=== Testing Macro Beta Module ===")
    macro_res = await macro_analysis_service.get_macro_score("BTCUSDT")
    print(f"Macro Score Result: {macro_res}")
    assert "macro_score" in macro_res
    assert "target_exposure" in macro_res

    print("\nAll tests passed!")

if __name__ == "__main__":
    asyncio.run(test_new_modules())
