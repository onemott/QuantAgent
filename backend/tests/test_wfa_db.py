import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, delete

from app.models.db_models import WFOSession, WFOWindowResult
from app.services.database import get_db

@pytest.mark.asyncio
async def test_wfo_sessions_and_windows_persistence():
    """
    Test that WFOSession and WFOWindowResult correctly store data,
    including large JSON payloads and multiple sliding window results.
    """
    now = datetime.now(timezone.utc)
    
    # 1. Prepare mock data
    # Generate a large equity curve JSON payload
    equity_curve = [{"t": (now + timedelta(days=i)).isoformat(), "v": 100000 + i * 100} for i in range(1000)]
    metrics = {
        "avg_oos_sharpe": 1.5,
        "total_oos_return": 0.25,
        "num_windows": 5,
        "stability_analysis": {
            "wfe_per_window": [0.5, 0.6, 0.7, 0.8, 0.9]
        }
    }
    
    session_id = None
    
    try:
        # 2. Insert WFOSession and WFOWindowResult
        async with get_db() as db:
            new_session = WFOSession(
                strategy_type="test_strategy_wfo",
                symbol="BTCUSDT",
                interval="1d",
                is_days=30,
                oos_days=10,
                step_days=10,
                start_time=now - timedelta(days=100),
                end_time=now,
                initial_capital=100000.0,
                status="completed",
                metrics=metrics,
                equity_curve=equity_curve
            )
            db.add(new_session)
            await db.flush()  # To populate new_session.id
            
            session_id = new_session.id
            
            # Insert 5 sliding windows
            for i in range(5):
                window = WFOWindowResult(
                    wfo_session_id=session_id,
                    window_index=i,
                    is_start_time=now - timedelta(days=100 - i * 10),
                    is_end_time=now - timedelta(days=70 - i * 10),
                    oos_start_time=now - timedelta(days=70 - i * 10),
                    oos_end_time=now - timedelta(days=60 - i * 10),
                    best_params={"param1": i, "param2": i * 2},
                    is_metrics={"sharpe": 1.0 + i * 0.1},
                    oos_metrics={"sharpe": 0.8 + i * 0.1},
                    wfe=0.5 + i * 0.1,
                    param_stability=0.9
                )
                db.add(window)
            
            # get_db context manager automatically commits here

        assert session_id is not None, "WFOSession ID should be generated"

        # 3. Read back and verify Data Persistence
        async with get_db() as db:
            # Verify session
            stmt = select(WFOSession).where(WFOSession.id == session_id)
            result = await db.execute(stmt)
            saved_session = result.scalar_one_or_none()
            
            assert saved_session is not None, "WFOSession should be saved"
            assert saved_session.strategy_type == "test_strategy_wfo"
            assert saved_session.symbol == "BTCUSDT"
            assert saved_session.status == "completed"
            
            # Check JSON field length and content
            assert len(saved_session.equity_curve) == 1000, "Equity curve should have 1000 items"
            assert saved_session.equity_curve[0]["v"] == 100000
            assert saved_session.equity_curve[-1]["v"] == 100000 + 999 * 100
            assert saved_session.metrics["num_windows"] == 5
            assert len(saved_session.metrics["stability_analysis"]["wfe_per_window"]) == 5
            
            # Verify windows
            stmt_win = select(WFOWindowResult).where(WFOWindowResult.wfo_session_id == session_id).order_by(WFOWindowResult.window_index)
            result_win = await db.execute(stmt_win)
            saved_windows = result_win.scalars().all()
            
            assert len(saved_windows) == 5, "Should have 5 window results saved"
            for i, win in enumerate(saved_windows):
                assert win.window_index == i
                assert win.best_params["param1"] == i
                assert win.best_params["param2"] == i * 2
                assert win.is_metrics["sharpe"] == 1.0 + i * 0.1
                assert win.wfe == 0.5 + i * 0.1
                assert win.is_start_time is not None
                assert win.oos_end_time is not None

    finally:
        # 4. Cleanup
        if session_id:
            async with get_db() as db:
                await db.execute(delete(WFOWindowResult).where(WFOWindowResult.wfo_session_id == session_id))
                await db.execute(delete(WFOSession).where(WFOSession.id == session_id))
                await db.commit()
