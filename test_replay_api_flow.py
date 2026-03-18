"""
测试历史回放 API 完整流程
测试创建会话 -> 启动回放 -> 查询状态
"""
import sys
sys.path.insert(0, "D:/Desktop/QuantAgent/backend")

import asyncio
import traceback
import time
from datetime import datetime, timezone

async def test_replay_api_flow():
    print("=" * 60)
    print("历史回放 API 完整流程测试")
    print("=" * 60)
    
    # 使用最近的可用数据时间
    start_time = datetime(2026, 3, 15, 0, 0, tzinfo=timezone.utc)
    end_time = datetime(2026, 3, 15, 0, 5, tzinfo=timezone.utc)
    
    print(f"\n[1] 测试参数:")
    print(f"    交易品种: BTCUSDT")
    print(f"    开始时间: {start_time}")
    print(f"    结束时间: {end_time}")
    print(f"    回放速度: 60x")
    print(f"    初始资金: $100,000")
    
    # 导入所有需要的模块
    from app.models.trading import ReplayCreateRequest
    from app.services.database import get_db
    from app.models.db_models import ReplaySession
    from sqlalchemy import select, update
    import uuid
    
    request = ReplayCreateRequest(
        strategy_id=1,
        symbol="BTCUSDT",
        start_time=start_time,
        end_time=end_time,
        speed=60,
        initial_capital=100000.0,
        strategy_type="ma",
        params={"fast_period": 10, "slow_period": 30}
    )
    
    session_id = f"TEST_API_{datetime.now().strftime('%Y%m%d')}_{uuid.uuid4().hex[:6]}"
    print(f"\n[2] 创建数据库会话:")
    print(f"    会话ID: {session_id}")
    
    # 创建数据库记录
    async with get_db() as db:
        new_session = ReplaySession(
            replay_session_id=session_id,
            strategy_id=request.strategy_id,
            strategy_type=request.strategy_type,
            params=request.params,
            symbol=request.symbol,
            start_time=request.start_time,
            end_time=request.end_time,
            speed=request.speed,
            initial_capital=request.initial_capital,
            status="pending"
        )
        db.add(new_session)
        await db.commit()
        print(f"    数据库记录已创建")
    
    # 模拟启动回放 (使用与 test_replay_task_direct.py 相同的逻辑)
    print(f"\n[3] 启动回放任务...")
    
    from app.core.bus import TradingBusImpl, ReplayConfig, PaperExecutionRouter
    from app.services.historical_replay_adapter import HistoricalReplayAdapter
    from app.strategies.ma_cross import MaCrossStrategy
    
    try:
        config = ReplayConfig(
            start_time=start_time,
            end_time=end_time,
            speed=60,
            initial_capital=100000.0
        )
        
        execution_router = PaperExecutionRouter()
        bus = TradingBusImpl(
            mode='HISTORICAL_REPLAY',
            data_adapter=None,
            execution_router=execution_router,
            session_id=session_id
        )
        adapter = HistoricalReplayAdapter(bus=bus, config=config)
        bus.data_adapter = adapter
        
        # 创建策略
        strategy = MaCrossStrategy(strategy_id='1', bus=bus)
        strategy.set_parameters({'fast_period': 10, 'slow_period': 30})
        print(f"    策略已创建")
        
        # 订阅数据
        await adapter.subscribe(['BTCUSDT'], '1m', strategy.on_bar)
        print(f"    数据加载: {len(adapter.data)} 条K线")
        
        if not adapter.data:
            raise Exception("没有加载到数据!")
        
        # 更新状态为运行中
        async with get_db() as db:
            await db.execute(
                update(ReplaySession)
                .where(ReplaySession.replay_session_id == session_id)
                .values(status="running")
            )
            await db.commit()
        print(f"    状态更新为: running")
        
        # 启动回放
        await adapter.start_playback()
        print(f"    回放完成!")
        
        # 更新状态为完成
        async with get_db() as db:
            await db.execute(
                update(ReplaySession)
                .where(ReplaySession.replay_session_id == session_id)
                .values(status="completed", current_timestamp=end_time)
            )
            await db.commit()
        print(f"    状态更新为: completed")
        
    except Exception as e:
        error_detail = f"{type(e).__name__}: {str(e)}"
        print(f"\n    回放错误: {error_detail}")
        traceback.print_exc()
        
        # 更新状态为失败
        try:
            async with get_db() as db:
                await db.execute(
                    update(ReplaySession)
                    .where(ReplaySession.replay_session_id == session_id)
                    .values(status="failed")
                )
                await db.commit()
        except:
            pass
        
        return False
    
    # 查询最终状态
    print(f"\n[4] 查询最终状态...")
    async with get_db() as db:
        stmt = select(ReplaySession).where(ReplaySession.replay_session_id == session_id)
        result = await db.execute(stmt)
        session = result.scalar_one_or_none()
        
        if session:
            print(f"    会话ID: {session.replay_session_id}")
            print(f"    状态: {session.status}")
            print(f"    策略: {session.strategy_type}")
            print(f"    品种: {session.symbol}")
            print(f"    开始时间: {session.start_time}")
            print(f"    结束时间: {session.end_time}")
            print(f"    当前时间: {session.current_timestamp}")
            print(f"    处理进度: {adapter.cursor}/{len(adapter.data)}")
    
    print("\n" + "=" * 60)
    print("测试完成!")
    print("=" * 60)
    
    return True

if __name__ == "__main__":
    try:
        result = asyncio.run(test_replay_api_flow())
        sys.exit(0 if result else 1)
    except Exception as e:
        print(f"\n测试失败: {type(e).__name__}: {e}")
        traceback.print_exc()
        sys.exit(1)
