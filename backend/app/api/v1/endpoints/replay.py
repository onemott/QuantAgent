import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional, List

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Query
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.database import get_db, get_db_session
from app.models.db_models import ReplaySession
from app.models.trading import (
    ReplayCreateRequest, ReplaySessionResponse, ReplayStatusResponse,
    ReplayJumpRequest, ValidDateRangeResponse
)
from app.services.clickhouse_service import clickhouse_service
from app.services.historical_replay_adapter import HistoricalReplayAdapter
from app.core.bus import TradingBusImpl, ReplayConfig, PaperExecutionRouter
from app.services.strategy_runner_service import strategy_runner_service
from app.services.paper_trading_service import paper_trading_service
from app.strategies.ma_cross import MaCrossStrategy
from app.strategies.signal_based_strategy import SignalBasedStrategy

logger = logging.getLogger(__name__)
router = APIRouter()

# Global store for active replay instances
# In a distributed system, this would be managed by a separate worker service
active_replays: Dict[str, HistoricalReplayAdapter] = {}

def get_strategy_class(strategy_type: str):
    """Factory to get the class-based strategy implementation."""
    # MA strategy has its own dedicated implementation
    if strategy_type == "ma":
        return MaCrossStrategy
    # All other strategies use the generic signal-based adapter
    # Supported: rsi, boll, macd, ema_triple, atr_trend, turtle, ichimoku, smart_beta, basis
    supported_types = {"rsi", "boll", "macd", "ema_triple", "atr_trend", "turtle", "ichimoku", "smart_beta", "basis"}
    if strategy_type in supported_types:
        return SignalBasedStrategy
    return None

@router.post("/create", response_model=ReplaySessionResponse)
async def create_replay_session(
    request: ReplayCreateRequest,
    db: AsyncSession = Depends(get_db_session)
):
    """Create a new historical replay session after validating dates."""
    # 1. Validate date range
    range_info = await clickhouse_service.get_valid_date_range(request.symbol)
    if not range_info["min_date"] or not range_info["max_date"]:
        raise HTTPException(status_code=400, detail=f"No historical data found for {request.symbol}")
    
    # Ensure requested range is within valid range
    start_utc = request.start_time.astimezone(timezone.utc)
    end_utc = request.end_time.astimezone(timezone.utc)
    
    # Simple check: if the requested start/end are completely outside the available range
    if start_utc > range_info["max_date"].replace(tzinfo=timezone.utc) or end_utc < range_info["min_date"].replace(tzinfo=timezone.utc):
        raise HTTPException(status_code=400, detail=f"Requested range {start_utc} - {end_utc} has no data. Available: {range_info['min_date']} - {range_info['max_date']}")

    # 2. Generate session ID
    session_id = f"REPLAY_{datetime.now().strftime('%Y%m%d')}_{uuid.uuid4().hex[:6]}"
    
    # 3. Save to database
    new_session = ReplaySession(
        replay_session_id=session_id,
        strategy_id=request.strategy_id,
        strategy_type=request.strategy_type,
        params=request.params or {},
        symbol=request.symbol,
        start_time=start_utc,
        end_time=end_utc,
        speed=request.speed,
        initial_capital=request.initial_capital,
        status="pending"
    )
    
    db.add(new_session)
    await db.commit()
    
    return ReplaySessionResponse(
        replay_session_id=session_id,
        status="pending",
        message="Replay session created successfully"
    )

@router.post("/{replay_session_id}/start", response_model=ReplaySessionResponse)
async def start_replay(
    replay_session_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db_session)
):
    """Start the historical replay in a background task."""
    logger.info(f"Start replay request received for session {replay_session_id}")
    
    try:
        # 1. Fetch session
        stmt = select(ReplaySession).where(ReplaySession.replay_session_id == replay_session_id)
        result = await db.execute(stmt)
        session = result.scalar_one_or_none()
        
        if not session:
            logger.warning(f"Replay session {replay_session_id} not found")
            raise HTTPException(status_code=404, detail="Replay session not found")
        
        if session.status == "running":
            return ReplaySessionResponse(replay_session_id=replay_session_id, status="running", message="Already running")

        # 2. Setup Replay Components
        try:
            config = ReplayConfig(
                start_time=session.start_time,
                end_time=session.end_time,
                speed=session.speed,
                initial_capital=session.initial_capital
            )
            
            # Create Bus and Adapter
            execution_router = PaperExecutionRouter()
            bus = TradingBusImpl(mode="HISTORICAL_REPLAY", data_adapter=None, execution_router=execution_router, session_id=replay_session_id)
            adapter = HistoricalReplayAdapter(bus=bus, config=config)
            bus.data_adapter = adapter
            
            active_replays[replay_session_id] = adapter
            logger.info(f"Replay components setup for session {replay_session_id}")
        except Exception as e:
            logger.error(f"Failed to setup replay components: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Component setup failed: {str(e)}")
        
        # 3. Update status to running
        try:
            session.status = "running"
            await db.commit()
            logger.info(f"Session {replay_session_id} status updated to running")
        except Exception as e:
            logger.error(f"Failed to update session status: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Database update failed: {str(e)}")
        
        # 4. Start strategy and playback in background
        # Capture needed values from session to avoid DetachedInstanceError in background task
        strategy_id_val = session.strategy_id
        strategy_type_val = session.strategy_type or "ma"
        strategy_params = session.params or {}
        symbol_val = session.symbol
        end_time_val = session.end_time

        async def run_replay_task():
            try:
                logger.info(f"Starting replay task for session {replay_session_id}")
                logger.info(f"Strategy type: {strategy_type_val}, params: {strategy_params}")
                
                # Load strategy class
                strategy_cls = get_strategy_class(strategy_type_val)
                if not strategy_cls:
                    raise ValueError(f"Unsupported strategy type: {strategy_type_val}")
                
                logger.info(f"Strategy class loaded: {strategy_cls.__name__}")
                
                # Handle strategy initialization (SignalBasedStrategy needs strategy_type)
                if strategy_cls is SignalBasedStrategy:
                    strategy = strategy_cls(strategy_id=str(strategy_id_val), bus=bus, strategy_type=strategy_type_val)
                else:
                    strategy = strategy_cls(strategy_id=str(strategy_id_val), bus=bus)
                strategy.set_parameters(strategy_params)
                logger.info(f"Strategy {strategy_type_val} initialized with params: {strategy_params}")
                
                # Subscribe the strategy to the bus
                logger.info(f"Subscribing to data for {symbol_val}")
                await adapter.subscribe([symbol_val], "1m", strategy.on_bar)
                logger.info(f"Subscribed, data loaded: {len(adapter.data)} bars")
                
                # Start playback
                logger.info("Starting playback...")
                await adapter.start_playback()
                logger.info("Playback started successfully")
                
                # Update status to completed
                async with get_db() as session_db:
                    await session_db.execute(
                        update(ReplaySession)
                        .where(ReplaySession.replay_session_id == replay_session_id)
                        .values(status="completed", current_timestamp=end_time_val)
                    )
                    await session_db.commit()
                    
            except Exception as e:
                import traceback
                error_details = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
                logger.error(f"Replay task failed for {replay_session_id}: {error_details}")
                try:
                    async with get_db() as session_db:
                        await session_db.execute(
                            update(ReplaySession)
                            .where(ReplaySession.replay_session_id == replay_session_id)
                            .values(status="failed")
                        )
                        await session_db.commit()
                except Exception as db_e:
                    logger.error(f"Failed to update session status to failed: {db_e}")
            finally:
                if replay_session_id in active_replays:
                    del active_replays[replay_session_id]

        background_tasks.add_task(run_replay_task)
        
        return ReplaySessionResponse(
            replay_session_id=replay_session_id,
            status="running",
            message="Historical replay started"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error starting replay {replay_session_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")

@router.get("/sessions", response_model=List[ReplaySessionResponse])
async def list_replay_sessions(
    db: AsyncSession = Depends(get_db_session),
    limit: int = Query(50, ge=1, le=100)
):
    """List recent replay sessions."""
    try:
        stmt = select(ReplaySession).order_by(ReplaySession.created_at.desc()).limit(limit)
        result = await db.execute(stmt)
        sessions = result.scalars().all()
        
        return [
            ReplaySessionResponse(
                replay_session_id=s.replay_session_id,
                status=s.status,
                message=f"Created at {s.created_at.strftime('%Y-%m-%d %H:%M:%S')}"
            ) for s in sessions
        ]
    except Exception as e:
        logger.error(f"Failed to list replay sessions: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Database query failed: {str(e)}")

@router.get("/{replay_session_id}/status", response_model=ReplayStatusResponse)
async def get_replay_status(
    replay_session_id: str,
    db: AsyncSession = Depends(get_db_session)
):
    """Query current status, progress and PNL of a replay session."""
    try:
        stmt = select(ReplaySession).where(ReplaySession.replay_session_id == replay_session_id)
        result = await db.execute(stmt)
        session = result.scalar_one_or_none()
        
        if not session:
            raise HTTPException(status_code=404, detail="Replay session not found")
        
        current_time = session.current_timestamp
        progress = 0.0
        pnl = 0.0
        
        # If active, get real-time info
        if replay_session_id in active_replays:
            adapter = active_replays[replay_session_id]
            current_time = adapter.get_current_simulated_time()
            if adapter.data and len(adapter.data) > 0:
                progress = min(1.0, adapter.cursor / len(adapter.data))
            else:
                progress = 0.0
                
        # Calculate progress if not active but has current_timestamp
        elif session.current_timestamp and session.start_time and session.end_time:
            total_duration = (session.end_time - session.start_time).total_seconds()
            if total_duration > 0:
                elapsed = (session.current_timestamp - session.start_time).total_seconds()
                progress = min(1.0, max(0.0, elapsed / total_duration))

        # Calculate PNL from trades and positions
        try:
            # 1. Realized PNL from trades
            from app.models.db_models import PaperTrade, PaperPosition
            from sqlalchemy import func
            pnl_stmt = select(func.sum(PaperTrade.pnl)).where(PaperTrade.session_id == replay_session_id)
            pnl_result = await db.execute(pnl_stmt)
            realized_pnl = float(pnl_result.scalar() or 0.0)
            
            # 2. Unrealized PNL from open positions
            unrealized_pnl = 0.0
            pos_stmt = select(PaperPosition).where(PaperPosition.session_id == replay_session_id)
            pos_result = await db.execute(pos_stmt)
            positions = pos_result.scalars().all()
            
            if positions:
                # Get current mark price for the replay
                mark_price = None
                if replay_session_id in active_replays:
                    adapter = active_replays[replay_session_id]
                    if adapter.data and adapter.cursor < len(adapter.data):
                        mark_price = adapter.data[adapter.cursor].close
                
                if mark_price:
                    for pos in positions:
                        qty = float(pos.quantity)
                        avg = float(pos.avg_price)
                        unrealized_pnl += (mark_price - avg) * qty
            
            pnl = realized_pnl + unrealized_pnl
        except Exception as e:
            logger.warning(f"Failed to calculate PNL for session {replay_session_id}: {e}")

        return ReplayStatusResponse(
            replay_session_id=replay_session_id,
            status=session.status,
            current_simulated_time=current_time,
            progress=progress,
            pnl=pnl
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get replay status for {replay_session_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")

@router.post("/{replay_session_id}/pause", response_model=ReplaySessionResponse)
async def pause_replay(
    replay_session_id: str,
    db: AsyncSession = Depends(get_db_session)
):
    """Pause the historical replay."""
    try:
        if replay_session_id not in active_replays:
            raise HTTPException(status_code=400, detail="Replay session is not active or already completed")
        
        adapter = active_replays[replay_session_id]
        adapter.pause_playback()
        
        # Update DB
        current_time = adapter.data[adapter.cursor].datetime if adapter.data and adapter.cursor < len(adapter.data) else None
        await db.execute(
            update(ReplaySession)
            .where(ReplaySession.replay_session_id == replay_session_id)
            .values(status="paused", current_timestamp=current_time)
        )
        await db.commit()
        
        return ReplaySessionResponse(
            replay_session_id=replay_session_id,
            status="paused",
            message="Historical replay paused"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to pause replay {replay_session_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Database update failed: {str(e)}")

@router.post("/{replay_session_id}/resume", response_model=ReplaySessionResponse)
async def resume_replay(
    replay_session_id: str,
    db: AsyncSession = Depends(get_db_session)
):
    """Resume a paused historical replay."""
    try:
        if replay_session_id not in active_replays:
            # If it's not in active_replays but status is paused, we might need to restart the task
            # However, for simplicity, let's assume it must be in active_replays (active task)
            raise HTTPException(status_code=400, detail="Replay session task is not active. Please start it again.")
        
        adapter = active_replays[replay_session_id]
        adapter.resume_playback()
        
        # Update DB
        await db.execute(
            update(ReplaySession)
            .where(ReplaySession.replay_session_id == replay_session_id)
            .values(status="running")
        )
        await db.commit()
        
        return ReplaySessionResponse(
            replay_session_id=replay_session_id,
            status="running",
            message="Historical replay resumed"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to resume replay {replay_session_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Database update failed: {str(e)}")

@router.post("/{replay_session_id}/jump", response_model=ReplaySessionResponse)
async def jump_replay(
    replay_session_id: str,
    request: ReplayJumpRequest,
    db: AsyncSession = Depends(get_db_session)
):
    """Jump to a specific timestamp in historical replay."""
    try:
        if replay_session_id not in active_replays:
            raise HTTPException(status_code=400, detail="Replay session is not active")
        
        adapter = active_replays[replay_session_id]
        target_utc = request.target_timestamp.astimezone(timezone.utc)
        
        adapter.set_start_timestamp(target_utc)
        # Also update the bus's simulated time
        await adapter.bus.jump_to(target_utc)
        
        # Update DB
        await db.execute(
            update(ReplaySession)
            .where(ReplaySession.replay_session_id == replay_session_id)
            .values(current_timestamp=target_utc)
        )
        await db.commit()
        
        return ReplaySessionResponse(
            replay_session_id=replay_session_id,
            status="paused", # Jump usually pauses or maintains pause as per SPEC
            message=f"Replay position jumped to {target_utc}"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to jump in replay {replay_session_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Jump operation failed: {str(e)}")

@router.get("/valid-date-range/{symbol}", response_model=ValidDateRangeResponse)
async def get_valid_date_range(symbol: str):
    """Query valid data range for a specific symbol from ClickHouse."""
    range_info = await clickhouse_service.get_valid_date_range(symbol.upper())
    return ValidDateRangeResponse(
        symbol=symbol.upper(),
        min_date=range_info["min_date"],
        max_date=range_info["max_date"],
        valid_dates=range_info["valid_dates"]
    )
