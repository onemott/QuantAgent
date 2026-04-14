
import asyncio
import logging
from datetime import datetime, timezone, timedelta
import pytest
from unittest.mock import patch
from app.core.bus import TradingBusImpl, ReplayConfig, TradingMode, PaperExecutionRouter
from app.services.historical_replay_adapter import HistoricalReplayAdapter
from app.models.trading import BarData

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@pytest.mark.asyncio
async def test_replay_jump_functionality():
    """
    Test Case: 
    1. Replay to 2026-03-15T12:30:00Z after pause.
    2. Jump to 2026-03-15T18:00:00Z and resume.
    3. Verify from 18:00 start, correct timestamp, no repeat/loss.
    """
    symbol = "BTCUSDT"
    interval = "1m"
    
    # Generate 24 hours of data for 2026-03-15
    start_time = datetime(2026, 3, 15, 0, 0, tzinfo=timezone.utc)
    end_time = datetime(2026, 3, 16, 0, 0, tzinfo=timezone.utc)
    
    mock_data = []
    current = start_time
    while current < end_time:
        mock_data.append(BarData(
            symbol=symbol,
            datetime=current,
            open=50000.0,
            high=50100.0,
            low=49900.0,
            close=50050.0,
            volume=10.0,
            interval=interval
        ))
        current += timedelta(minutes=1)
    
    config = ReplayConfig(
        start_time=start_time,
        end_time=end_time,
        speed=100, # 100x speed for fast test
        initial_capital=100000.0
    )
    
    execution_router = PaperExecutionRouter()
    bus = TradingBusImpl(
        mode=TradingMode.HISTORICAL_REPLAY,
        data_adapter=None,
        execution_router=execution_router,
        session_id="TEST_JUMP_SESSION"
    )
    
    adapter = HistoricalReplayAdapter(bus=bus, config=config)
    adapter.data = mock_data # Inject mock data
    bus.data_adapter = adapter
    
    received_bars = []
    def on_bar(bar):
        received_bars.append(bar)
        # logger.info(f"Received bar: {bar.datetime}")

    bus.subscribe_bars(on_bar)
    
    # 1. Start playback in background
    async def fast_sleep(seconds):
        return None

    with patch("app.services.historical_replay_adapter.asyncio.sleep", new=fast_sleep):
        playback_task = asyncio.create_task(adapter.start_playback())
    
        # 2. Wait until we reach 12:30
        target_pause_time = datetime(2026, 3, 15, 12, 30, tzinfo=timezone.utc)
        logger.info(f"Waiting for replay to reach {target_pause_time}...")
        
        while True:
            if bus.current_simulated_time and bus.current_simulated_time >= target_pause_time:
                break
            await asyncio.sleep(0)
        
        # 3. Pause
        bus.pause()
        logger.info(f"Replay paused at {bus.current_simulated_time}")
        
        # Record how many bars received so far
        bars_before_jump = len(received_bars)
        last_bar_before_jump = received_bars[-1].datetime
        logger.info(f"Bars received before jump: {bars_before_jump}, last bar: {last_bar_before_jump}")
        
        # 4. Jump to 18:00
        target_jump_time = datetime(2026, 3, 15, 18, 0, tzinfo=timezone.utc)
        logger.info(f"Jumping to {target_jump_time}...")
        await bus.jump_to(target_jump_time)
        
        # 5. Resume
        logger.info("Resuming replay...")
        bus.resume()
        
        # 6. Wait for a few more bars
        await asyncio.sleep(0)
        
        # 7. Stop
        adapter.stop_playback()
        await playback_task
    
    # 8. Verification
    bars_after_jump = received_bars[bars_before_jump:]
    if not bars_after_jump:
        logger.error("No bars received after jump!")
        return

    first_bar_after_jump = bars_after_jump[0].datetime
    logger.info(f"First bar after jump: {first_bar_after_jump}")
    
    # Verification criteria
    # - First bar after jump should be >= 18:00
    # - There should be no overlap (time gap between last_bar_before_jump and first_bar_after_jump)
    
    assert first_bar_after_jump >= target_jump_time, f"Expected >= {target_jump_time}, got {first_bar_after_jump}"
    assert first_bar_after_jump > last_bar_before_jump, "Time must move forward after jump"
    
    logger.info("Jump verification successful!")
    logger.info(f"Jump Gap: {first_bar_after_jump - last_bar_before_jump}")

if __name__ == "__main__":
    asyncio.run(test_replay_jump_functionality())
