
import asyncio
import time
import logging
from datetime import datetime, timedelta
import pytest
from unittest.mock import patch
from app.core.bus import TradingBusImpl, ReplayConfig, TradingMode, PaperExecutionRouter
from app.services.historical_replay_adapter import HistoricalReplayAdapter
from app.models.trading import BarData

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@pytest.mark.asyncio
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
    
    execution_router = PaperExecutionRouter()
    bus = TradingBusImpl(
        mode=TradingMode.HISTORICAL_REPLAY,
        data_adapter=None,
        execution_router=execution_router,
        session_id="TEST_SPEED_SESSION",
    )

    adapter = HistoricalReplayAdapter(bus=bus, config=config)
    bus.data_adapter = adapter

    mock_data = []
    current = start_time
    while current <= end_time:
        mock_data.append(
            BarData(
                symbol=symbol,
                interval=interval,
                datetime=current,
                open=50000.0,
                high=50100.0,
                low=49900.0,
                close=50050.0,
                volume=100.0,
            )
        )
        current += timedelta(minutes=1)

    adapter.data = mock_data
    adapter.cursor = 0

    bars_received = 0

    def bar_callback(bar: BarData):
        nonlocal bars_received
        bars_received += 1

    bus.subscribe_bars(bar_callback)
    start_real_time = time.time()

    async def fast_sleep(_seconds):
        return None

    with patch("app.services.historical_replay_adapter.asyncio.sleep", new=fast_sleep):
        await adapter.start_playback()
    end_real_time = time.time()
    elapsed_time = end_real_time - start_real_time

    assert bars_received == len(mock_data)
    assert elapsed_time < 1.0

if __name__ == "__main__":
    asyncio.run(test_replay_60x_speed())
