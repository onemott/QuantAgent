"""
测试不同倍速是否能够正常创建和执行回放
使用mock数据，测试速度极快
"""

import asyncio
import time
import logging
from datetime import datetime, timedelta, timezone
import pytest
from unittest.mock import patch
from app.core.bus import TradingBusImpl, ReplayConfig, TradingMode, PaperExecutionRouter
from app.services.historical_replay_adapter import HistoricalReplayAdapter
from app.models.trading import BarData

logging.basicConfig(level=logging.WARNING)  # 减少日志输出
logger = logging.getLogger(__name__)


async def run_speed_case(speed: int, bars_count: int = 60):
    """
    测试指定倍速是否正常工作
    使用mock数据，无需数据库和网络
    """
    symbol = "BTCUSDT"
    interval = "1m"
    
    # 设置时间范围
    start_time = datetime(2026, 3, 15, 0, 0, tzinfo=timezone.utc)
    end_time = start_time + timedelta(minutes=bars_count - 1)
    
    config = ReplayConfig(
        start_time=start_time,
        end_time=end_time,
        speed=speed,
        initial_capital=100000.0
    )
    
    execution_router = PaperExecutionRouter()
    # NOTE: No session_id — _compute_completion_metrics() checks for it and skips
    # DB calls when absent, so tests can run without database connectivity.
    bus = TradingBusImpl(
        mode=TradingMode.HISTORICAL_REPLAY,
        data_adapter=None,
        execution_router=execution_router,
    )
    
    adapter = HistoricalReplayAdapter(bus=bus, config=config)
    bus.data_adapter = adapter
    
    # Mock 数据
    mock_data = []
    for i in range(bars_count):
        mock_bar = BarData(
            symbol=symbol,
            interval=interval,
            datetime=start_time + timedelta(minutes=i),
            open=50000.0 + i,
            high=50100.0 + i,
            low=49900.0 + i,
            close=50050.0 + i,
            volume=100.0
        )
        mock_data.append(mock_bar)
    
    adapter.data = mock_data
    adapter.cursor = 0
    
    # 计数收到的bar
    bars_received = 0
    
    def bar_callback(bar: BarData):
        nonlocal bars_received
        bars_received += 1
    
    # Register callback through the bus's subscription mechanism.
    # start_playback() calls bus.publish_bar() which dispatches to bar_subscribers.
    bus.subscribe_bars(bar_callback)
    
    start_real_time = time.time()
    
    async def fast_sleep(_seconds):
        return None

    with patch("app.services.historical_replay_adapter.asyncio.sleep", new=fast_sleep):
        await adapter.start_playback()
    
    elapsed_time = time.time() - start_real_time
    
    # 计算预期时间
    if speed == -1:
        expected_time = bars_count * 0.001  # 假设每根1ms
    else:
        expected_time = bars_count / speed
    
    # 判断是否通过
    passed = bars_received == bars_count
    
    adapter.stop_playback()
    
    return {
        "speed": speed,
        "bars_received": bars_received,
        "elapsed_time": elapsed_time,
        "expected_time": expected_time,
        "passed": passed
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("speed", [1, 10, 60, 100, 500, 1000, -1])
async def test_replay_all_supported_speeds(speed: int):
    result = await run_speed_case(speed, bars_count=5)

    assert result["passed"]
    assert result["bars_received"] == 5


async def main():
    """测试所有倍速"""
    speeds_to_test = [1, 10, 60, 100, 500, 1000, -1]
    
    print("=" * 60)
    print("倍速功能测试")
    print("=" * 60)
    
    for speed in speeds_to_test:
        result = await run_speed_case(speed, bars_count=60)
        status = "PASS" if result["passed"] else "FAIL"
        print(f"  {speed:>6}x: {status} | 收到 {result['bars_received']} 根K线 | 耗时 {result['elapsed_time']:.3f}s")
    
    print("=" * 60)
    print("测试完成")


if __name__ == "__main__":
    asyncio.run(main())
