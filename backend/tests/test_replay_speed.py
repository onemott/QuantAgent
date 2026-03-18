
import asyncio
import time
import logging
from datetime import datetime, timedelta
from app.core.bus import TradingBusImpl, ReplayConfig, TradingMode, PaperExecutionRouter
from app.services.historical_replay_adapter import HistoricalReplayAdapter
from app.models.trading import BarData

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_replay_60x_speed():
    """
    Test Case: Set 60x speed, replay 1 hour of data, verify it takes about 1 minute.
    """
    symbol = "BTCUSDT"
    interval = "1m"
    start_time = datetime(2026, 3, 15, 0, 0)
    end_time = start_time + timedelta(hours=1)
    speed = 60
    
    config = ReplayConfig(
        start_time=start_time,
        end_time=end_time,
        speed=speed,
        initial_capital=100000.0
    )
    
    # Mock execution router
    execution_router = PaperExecutionRouter()
    
    # Initialize Bus
    bus = TradingBusImpl(
        mode=TradingMode.HISTORICAL_REPLAY,
        data_adapter=None, # Will be set by adapter
        execution_router=execution_router,
        session_id="TEST_SPEED_SESSION"
    )
    
    # Initialize Adapter
    adapter = HistoricalReplayAdapter(bus=bus, config=config)
    bus.data_adapter = adapter
    
    # Count bars received
    bars_received = 0
    async def bar_callback(bar: BarData):
        nonlocal bars_received
        bars_received += 1
        if bars_received % 10 == 0:
            logger.info(f"Received {bars_received} bars, current bar time: {bar.datetime}")

    # Subscribe and load data
    await adapter.subscribe([symbol], interval, bar_callback)
    
    if not adapter.data:
        logger.error("No data loaded for test!")
        return

    logger.info(f"Starting replay of {len(adapter.data)} bars at {speed}x speed...")
    
    start_real_time = time.time()
    
    # Run playback
    await adapter.start_playback()
    
    end_real_time = time.time()
    elapsed_time = end_real_time - start_real_time
    
    # 1 hour of data at 60x should take 60 seconds
    expected_time = 60.0
    error_margin = 0.1 # 10%
    
    logger.info("="*50)
    logger.info(f"Replay Summary:")
    logger.info(f"Bars Replayed: {bars_received}")
    logger.info(f"Elapsed Time: {elapsed_time:.2f} seconds")
    logger.info(f"Expected Time: {expected_time:.2f} seconds")
    
    diff = abs(elapsed_time - expected_time)
    error_pct = (diff / expected_time) * 100
    
    logger.info(f"Error: {error_pct:.2f}%")
    
    if error_pct < 10.0:
        logger.info("PASS: Speed test within 10% error margin.")
    else:
        logger.error("FAIL: Speed test outside 10% error margin.")

if __name__ == "__main__":
    asyncio.run(test_replay_60x_speed())
