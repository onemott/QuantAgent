
import asyncio
import logging
from datetime import datetime, timedelta

logging.basicConfig(level=logging.DEBUG)

async def test_replay_directly():
    from app.core.bus import TradingBusImpl, ReplayConfig, TradingMode, PaperExecutionRouter
    from app.services.historical_replay_adapter import HistoricalReplayAdapter
    from app.strategies.ma_cross import MaCrossStrategy
    
    symbol = "BTCUSDT"
    interval = "1m"
    start_time = datetime(2026, 3, 15, 0, 0)
    end_time = start_time + timedelta(minutes=5)
    speed = 1
    
    config = ReplayConfig(
        start_time=start_time,
        end_time=end_time,
        speed=speed,
        initial_capital=100000.0
    )
    
    execution_router = PaperExecutionRouter()
    bus = TradingBusImpl(
        mode=TradingMode.HISTORICAL_REPLAY,
        data_adapter=None,
        execution_router=execution_router,
        session_id="TEST_DIRECT"
    )
    
    adapter = HistoricalReplayAdapter(bus=bus, config=config)
    bus.data_adapter = adapter
    
    # Create strategy
    strategy = MaCrossStrategy(strategy_id="test_strategy", bus=bus)
    strategy.set_parameters({"fast_period": 10, "slow_period": 30})
    
    print("Subscribing to data...")
    await adapter.subscribe([symbol], interval, strategy.on_bar)
    
    print(f"Data loaded: {len(adapter.data)} bars")
    
    if not adapter.data:
        print("ERROR: No data loaded!")
        return
    
    print("Starting playback...")
    await adapter.start_playback()
    
    print(f"Final cursor position: {adapter.cursor}")
    print(f"Total bars: {len(adapter.data)}")
    print("Replay completed!")

if __name__ == "__main__":
    asyncio.run(test_replay_directly())
