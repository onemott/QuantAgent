"""
历史回放功能验证测试
测试从数据加载到回放完成的完整流程
"""
import sys
sys.path.insert(0, "D:/Desktop/QuantAgent/backend")

import asyncio
from datetime import datetime, timezone

async def verify_replay():
    print("=" * 60)
    print("历史回放功能验证测试")
    print("=" * 60)
    
    from app.services.clickhouse_service import clickhouse_service
    from app.core.bus import TradingBusImpl, ReplayConfig, PaperExecutionRouter
    from app.services.historical_replay_adapter import HistoricalReplayAdapter
    from app.strategies.ma_cross import MaCrossStrategy
    
    # 1. 验证数据可用性
    print("\n[1] 数据可用性验证...")
    range_info = await clickhouse_service.get_valid_date_range('BTCUSDT')
    print(f"    数据范围: {range_info['min_date'].date()} 至 {range_info['max_date'].date()}")
    print(f"    有效天数: {len(range_info['valid_dates'])} 天")
    assert len(range_info['valid_dates']) > 0, "没有可用数据!"
    
    # 2. 设置测试范围
    test_start = datetime(2026, 3, 15, 0, 0, tzinfo=timezone.utc)
    test_end = datetime(2026, 3, 15, 0, 5, tzinfo=timezone.utc)
    
    # 3. 创建回放组件
    print("\n[2] 创建回放组件...")
    config = ReplayConfig(start_time=test_start, end_time=test_end, speed=60, initial_capital=100000.0)
    bus = TradingBusImpl(mode='HISTORICAL_REPLAY', data_adapter=None, 
                         execution_router=PaperExecutionRouter(), session_id='VERIFY_TEST')
    adapter = HistoricalReplayAdapter(bus=bus, config=config)
    bus.data_adapter = adapter
    
    # 4. 创建策略
    print("\n[3] 创建策略...")
    strategy = MaCrossStrategy(strategy_id='1', bus=bus)
    strategy.set_parameters({'fast_period': 10, 'slow_period': 30})
    
    # 5. 订阅数据
    print("\n[4] 订阅数据...")
    await adapter.subscribe(['BTCUSDT'], '1m', strategy.on_bar)
    print(f"    加载数据: {len(adapter.data)} 条K线")
    assert len(adapter.data) > 0, "数据加载失败!"
    
    # 6. 验证时间计算
    print("\n[5] 验证时间计算...")
    current_time = adapter.get_current_simulated_time()
    print(f"    当前模拟时间: {current_time}")
    assert current_time.tzinfo is not None, "时区信息丢失!"
    
    # 7. 执行回放
    print("\n[6] 执行回放...")
    await adapter.start_playback()
    print(f"    回放完成: 处理 {adapter.cursor}/{len(adapter.data)} 条")
    assert adapter.cursor == len(adapter.data), "回放未完成!"
    
    # 8. 验证最终状态
    print("\n[7] 验证最终状态...")
    final_time = adapter.get_current_simulated_time()
    print(f"    最终时间: {final_time}")
    print(f"    总进度: {(adapter.cursor / len(adapter.data) * 100):.1f}%")
    
    print("\n" + "=" * 60)
    print("验证成功! 历史回放功能正常工作。")
    print("=" * 60)
    return True

if __name__ == "__main__":
    try:
        result = asyncio.run(verify_replay())
        sys.exit(0 if result else 1)
    except Exception as e:
        print(f"\n验证失败: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
