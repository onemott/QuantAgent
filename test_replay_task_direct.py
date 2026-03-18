
import sys
sys.path.insert(0, "D:/Desktop/QuantAgent/backend")

import asyncio
import traceback
from datetime import datetime

async def test_replay_task():
    from app.core.bus import TradingBusImpl, ReplayConfig, TradingMode, PaperExecutionRouter
    from app.services.historical_replay_adapter import HistoricalReplayAdapter
    from app.strategies.ma_cross import MaCrossStrategy
    
    replay_session_id = "TEST_DIRECT_TASK"
    strategy_id_val = 1
    strategy_type_val = "ma"
    strategy_params = {"fast_period": 10, "slow_period": 30}
    symbol_val = "BTCUSDT"
    end_time_val = datetime(2026, 3, 15, 0, 5)
    
    try:
        # Setup components (same as in API)
        start_time = datetime(2026, 3, 15, 0, 0)
        config = ReplayConfig(
            start_time=start_time,
            end_time=end_time_val,
            speed=1,
            initial_capital=100000.0
        )
        
        execution_router = PaperExecutionRouter()
        bus = TradingBusImpl(
            mode="HISTORICAL_REPLAY",
            data_adapter=None,
            execution_router=execution_router,
            session_id=replay_session_id
        )
        adapter = HistoricalReplayAdapter(bus=bus, config=config)
        bus.data_adapter = adapter
        
        print(f"Components created for session {replay_session_id}")
        
        # Load strategy class
        print(f"Loading strategy class for {strategy_type_val}...")
        if strategy_type_val == "ma":
            strategy_cls = MaCrossStrategy
        else:
            raise ValueError(f"Unsupported strategy type: {strategy_type_val}")
        
        print(f"Strategy class: {strategy_cls.__name__}")
        
        # Create strategy
        print("Creating strategy instance...")
        strategy = strategy_cls(strategy_id=str(strategy_id_val), bus=bus)
        strategy.set_parameters(strategy_params)
        print(f"Strategy created with params: {strategy_params}")
        
        # Subscribe
        print(f"Subscribing to data for {symbol_val}...")
        await adapter.subscribe([symbol_val], "1m", strategy.on_bar)
        print(f"Subscribed, data loaded: {len(adapter.data)} bars")
        
        if not adapter.data:
            raise Exception("No data loaded for replay!")
        
        # Start playback
        print("Starting playback...")
        await adapter.start_playback()
        print("Playback completed successfully!")
        
        return True
        
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        print("\nFull traceback:")
        traceback.print_exc()
        return False

if __name__ == "__main__":
    result = asyncio.run(test_replay_task())
    print(f"\nTest result: {'SUCCESS' if result else 'FAILED'}")
