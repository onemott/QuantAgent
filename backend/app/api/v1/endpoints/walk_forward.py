"""
Walk-Forward Optimization API Endpoints
"""

import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from pydantic import BaseModel, Field, ConfigDict

from app.services.database import get_db
from app.models.db_models import WFOSession, WFOWindowResult
from app.services.clickhouse_service import clickhouse_service
from app.services.walk_forward.optimizer import WalkForwardOptimizer
from sqlalchemy import select

logger = logging.getLogger(__name__)
router = APIRouter()

# ─────────────────────────────────────────────────────────────────────────────
# Request / Response Models
# ─────────────────────────────────────────────────────────────────────────────

class WFORunRequest(BaseModel):
    strategy_type: str = Field(..., description="Strategy identifier, e.g., 'ma', 'rsi'")
    symbol: str = Field("BTCUSDT", description="Trading pair symbol")
    interval: str = Field("1d", description="Candle interval, e.g., '1h', '1d'")
    is_days: int = Field(180, description="In-sample window size in days")
    oos_days: int = Field(60, description="Out-of-sample window size in days")
    step_days: int = Field(60, description="Step size in days")
    start_time: datetime = Field(..., description="Start time for the whole dataset")
    end_time: datetime = Field(..., description="End time for the whole dataset")
    initial_capital: float = Field(10000.0, description="Initial capital for backtesting")
    n_trials: int = Field(30, description="Number of trials for Optuna optimization")
    use_numba: bool = Field(False, description="Whether to use numba for backtest acceleration")
    embargo_days: int = Field(0, description="Embargo days to prevent data leakage")

class WFORunResponse(BaseModel):
    session_id: int
    message: str

class WFOSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    strategy_type: str
    symbol: str
    interval: str
    is_days: int
    oos_days: int
    step_days: int
    start_time: datetime
    end_time: datetime
    initial_capital: float
    status: str
    error_message: Optional[str]
    metrics: Dict[str, Any]
    equity_curve: List[Dict[str, Any]]
    created_at: datetime
    updated_at: Optional[datetime]

class WFOWindowResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    wfo_session_id: int
    window_index: int
    is_start_time: datetime
    is_end_time: datetime
    oos_start_time: datetime
    oos_end_time: datetime
    best_params: Dict[str, Any]
    is_metrics: Dict[str, Any]
    oos_metrics: Dict[str, Any]
    wfe: Optional[float]
    param_stability: Optional[float]
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# Background Task
# ─────────────────────────────────────────────────────────────────────────────

async def run_wfo_task(session_id: int, req: WFORunRequest):
    """
    Background task to execute Walk-Forward Optimization.
    Fetches data from ClickHouse and runs the optimizer.
    Updates the WFOSession and creates WFOWindowResult records.
    """
    try:
        symbol_clean = req.symbol.upper()
        
        df = await clickhouse_service.get_klines_dataframe(
            symbol=symbol_clean,
            interval=req.interval,
            start=req.start_time,
            end=req.end_time,
            limit=500000
        )
        
        if df is None or len(df) < 50:
            async with get_db() as session_db:
                stmt = select(WFOSession).where(WFOSession.id == session_id)
                result = await session_db.execute(stmt)
                session_obj = result.scalar_one_or_none()
                if session_obj:
                    session_obj.status = "failed"
                    session_obj.error_message = f"ClickHouse 中 {symbol_clean} {req.interval} 的历史数据不足，请先补充数据。"
                    await session_db.commit()
            return

        async with get_db() as session_db:
            stmt = select(WFOSession).where(WFOSession.id == session_id)
            result = await session_db.execute(stmt)
            session_obj = result.scalar_one_or_none()
            if session_obj:
                session_obj.status = "running"
                await session_db.commit()
            else:
                return

        # Run Walk-Forward Optimizer (Long running, outside db session)
        optimizer = WalkForwardOptimizer(df, req.strategy_type, req.initial_capital)
        wfo_result = await optimizer.run_wfo(
            is_days=req.is_days,
            oos_days=req.oos_days,
            n_trials=req.n_trials,
            use_numba=req.use_numba,
            embargo_days=req.embargo_days
        )
        
        if "error" in wfo_result:
            async with get_db() as session_db:
                stmt = select(WFOSession).where(WFOSession.id == session_id)
                result = await session_db.execute(stmt)
                session_obj = result.scalar_one_or_none()
                if session_obj:
                    session_obj.status = "failed"
                    session_obj.error_message = wfo_result["error"]
                    await session_db.commit()
            return
        
        # Fetch the session again to update results
        async with get_db() as session_db:
            stmt = select(WFOSession).where(WFOSession.id == session_id)
            result = await session_db.execute(stmt)
            session_obj = result.scalar_one_or_none()
            if session_obj:
                session_obj.status = "completed"
                
                # Assign metrics
                session_obj.metrics = {
                    "avg_oos_sharpe": wfo_result["metrics"].get("avg_oos_sharpe", 0.0),
                    "total_oos_return": wfo_result["metrics"].get("total_oos_return", 0.0),
                    "num_windows": wfo_result["metrics"].get("num_windows", 0),
                    "stability_analysis": wfo_result.get("stability_analysis", {})
                }
                
                # Assign stitched equity curve
                stitched = wfo_result.get("stitched_oos_performance", {})
                if stitched:
                    session_obj.equity_curve = [
                        {"t": t, "v": round(v, 2)} 
                        for t, v in zip(stitched.get("dates", []), stitched.get("equity_curve", []))
                    ]
                
                # Save window results
                stability_analysis = wfo_result.get("stability_analysis", {})
                wfe_list = stability_analysis.get("wfe_per_window", [])
                
                for i, w in enumerate(wfo_result.get("walk_forward_results", [])):
                    win = WFOWindowResult(
                        wfo_session_id=session_id,
                        window_index=w["window_index"],
                        is_start_time=datetime.fromisoformat(w["is_period"][0]),
                        is_end_time=datetime.fromisoformat(w["is_period"][1]),
                        oos_start_time=datetime.fromisoformat(w["oos_period"][0]),
                        oos_end_time=datetime.fromisoformat(w["oos_period"][1]),
                        best_params=w["best_params"],
                        is_metrics={"sharpe": w.get("is_sharpe", 0.0)},
                        oos_metrics={
                            "sharpe": w.get("oos_sharpe", 0.0),
                            "return": w.get("oos_return", 0.0),
                            "drawdown": w.get("oos_drawdown", 0.0)
                        },
                        wfe=w.get("wfe", wfe_list[i] if i < len(wfe_list) else None),
                        param_stability=stability_analysis.get("parameter_stability_scores", {}).get(str(i))
                    )
                    session_db.add(win)
                    
                await session_db.commit()
                
    except Exception as e:
        logger.exception(f"WFO task failed for session {session_id}: {e}")
        try:
            async with get_db() as session_db:
                stmt = select(WFOSession).where(WFOSession.id == session_id)
                result = await session_db.execute(stmt)
                session_obj = result.scalar_one_or_none()
                if session_obj:
                    session_obj.status = "failed"
                    session_obj.error_message = str(e)
                    await session_db.commit()
        except Exception as inner_e:
            logger.error(f"Failed to update WFO session status to failed: {inner_e}")


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/run", response_model=WFORunResponse)
async def run_wfo_endpoint(req: WFORunRequest, background_tasks: BackgroundTasks):
    """
    Start a Walk-Forward Optimization session.
    Enforces ClickHouse data source. If data is missing, raises an error immediately
    or fails the background task.
    """
    symbol_clean = req.symbol.upper()
    
    # Fast check: ping ClickHouse to ensure it is alive
    if not await clickhouse_service.ping():
        raise HTTPException(
            status_code=503,
            detail="ClickHouse 服务不可用，Walk-Forward Optimization 需要依赖 ClickHouse 历史数据。"
        )
        
    # Check if we have at least *some* data for this symbol
    count = await clickhouse_service.count_klines(symbol_clean, req.interval)
    if count == 0:
        raise HTTPException(
            status_code=400,
            detail=f"ClickHouse 中没有 {symbol_clean} {req.interval} 的数据，请先同步数据。"
        )

    try:
        async with get_db() as db:
            session = WFOSession(
                strategy_type=req.strategy_type,
                symbol=symbol_clean,
                interval=req.interval,
                is_days=req.is_days,
                oos_days=req.oos_days,
                step_days=req.step_days,
                start_time=req.start_time,
                end_time=req.end_time,
                initial_capital=req.initial_capital,
                status="pending"
            )
            db.add(session)
            await db.flush()
            session_id = session.id
            await db.commit()
            
    except Exception as e:
        logger.error(f"Failed to create WFO session: {e}")
        raise HTTPException(status_code=500, detail="创建 WFO 会话失败")

    # Add to background tasks
    background_tasks.add_task(run_wfo_task, session_id, req)
    
    return WFORunResponse(
        session_id=session_id,
        message="Walk-Forward Optimization 任务已在后台启动"
    )


@router.get("/sessions/{id}", response_model=WFOSessionResponse)
async def get_wfo_session(id: int):
    """
    Retrieve the status and overall results of a specific WFO session.
    """
    async with get_db() as db:
        stmt = select(WFOSession).where(WFOSession.id == id)
        result = await db.execute(stmt)
        session = result.scalar_one_or_none()
        
        if not session:
            raise HTTPException(status_code=404, detail="WFO 会话不存在")
            
        return session


@router.get("/sessions/{id}/windows", response_model=List[WFOWindowResultResponse])
async def get_wfo_session_windows(id: int):
    """
    Retrieve the individual window results (In-Sample and Out-of-Sample metrics)
    for a specific WFO session.
    """
    async with get_db() as db:
        # First verify session exists
        stmt_session = select(WFOSession).where(WFOSession.id == id)
        result_session = await db.execute(stmt_session)
        if not result_session.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="WFO 会话不存在")
            
        # Get windows
        stmt = select(WFOWindowResult).where(WFOWindowResult.wfo_session_id == id).order_by(WFOWindowResult.window_index.asc())
        result = await db.execute(stmt)
        windows = result.scalars().all()
        
        return windows
