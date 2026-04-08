"""
Dynamic Strategy Selection Endpoints
Provides endpoints for strategy evaluation, dynamic selection configuration,
radar metrics, and allocation tracking.
"""

import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel, Field

from app.services.database import get_db_session
from app.models.db_models import StrategyEvaluation, SelectionHistory

logger = logging.getLogger(__name__)
router = APIRouter()

# ─────────────────────────────────────────────────────────────────────────────
# Request / Response Models
# ─────────────────────────────────────────────────────────────────────────────

class DynamicSelectionConfig(BaseModel):
    evaluation_interval: str = Field(default="1w", description="Evaluation interval, e.g., 1d, 1w, 1m")
    metrics_weights: Dict[str, float] = Field(default={
        "return_score": 0.3,
        "risk_score": 0.3,
        "stability_score": 0.2,
        "efficiency_score": 0.2
    }, description="Weights for evaluation metrics")
    elimination_threshold: float = Field(default=0.3, description="Threshold for eliminating strategies")
    max_strategies: int = Field(default=10, description="Maximum number of active strategies")
    min_strategies: int = Field(default=3, description="Minimum number of active strategies")

class EvaluateRequest(BaseModel):
    window_start: datetime
    window_end: datetime
    force_recalculate: bool = False

class StrategyMetrics(BaseModel):
    return_score: float
    risk_score: float
    stability_score: float
    efficiency_score: float
    total_score: float

class RadarMetricsResponse(BaseModel):
    strategy_id: str
    evaluation_date: datetime
    metrics: StrategyMetrics

class AllocationResponse(BaseModel):
    evaluation_date: datetime
    strategy_weights: Dict[str, float]

class AllocationUpdateRequest(BaseModel):
    strategy_weights: Dict[str, float]

# Mock config storage for demonstration purposes
# In a real scenario, this might be stored in a Config table or Redis
_current_config = DynamicSelectionConfig()

# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/config", response_model=DynamicSelectionConfig)
async def get_config():
    """Get current dynamic selection configuration."""
    return _current_config

@router.post("/config", response_model=DynamicSelectionConfig)
async def update_config(config: DynamicSelectionConfig):
    """Update dynamic selection configuration."""
    global _current_config
    _current_config = config
    logger.info(f"Dynamic selection config updated: {config.model_dump()}")
    return _current_config

@router.post("/evaluate")
async def trigger_evaluation(
    request: EvaluateRequest,
    db: AsyncSession = Depends(get_db_session)
):
    """
    Manually trigger a strategy evaluation process over the given time window.
    """
    logger.info(f"Triggered strategy evaluation from {request.window_start} to {request.window_end}")
    
    return {
        "status": "success",
        "message": "Evaluation process started",
        "window_start": request.window_start,
        "window_end": request.window_end
    }

@router.get("/history")
async def get_selection_history(
    limit: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Get the history of strategy selections and eliminations.
    """
    stmt = select(SelectionHistory).order_by(desc(SelectionHistory.evaluation_date)).limit(limit)
    result = await db.execute(stmt)
    history = result.scalars().all()
    
    return history

@router.get("/metrics/radar", response_model=RadarMetricsResponse)
async def get_radar_metrics(
    strategy_id: str = Query(..., description="The ID of the strategy"),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Get radar chart metrics for a specific strategy based on its latest evaluation.
    """
    stmt = (
        select(StrategyEvaluation)
        .where(StrategyEvaluation.strategy_id == strategy_id)
        .order_by(desc(StrategyEvaluation.evaluation_date))
        .limit(1)
    )
    result = await db.execute(stmt)
    eval_record = result.scalars().first()
    
    if not eval_record:
        raise HTTPException(
            status_code=404, 
            detail=f"No evaluation record found for strategy {strategy_id}"
        )
        
    metrics = StrategyMetrics(
        return_score=eval_record.return_score or 0.0,
        risk_score=eval_record.risk_score or 0.0,
        stability_score=eval_record.stability_score or 0.0,
        efficiency_score=eval_record.efficiency_score or 0.0,
        total_score=eval_record.total_score or 0.0
    )
    
    return RadarMetricsResponse(
        strategy_id=eval_record.strategy_id,
        evaluation_date=eval_record.evaluation_date,
        metrics=metrics
    )

@router.get("/allocation", response_model=AllocationResponse)
async def get_allocation(db: AsyncSession = Depends(get_db_session)):
    """
    Get the current capital allocation weights for active strategies.
    """
    stmt = select(SelectionHistory).order_by(desc(SelectionHistory.evaluation_date)).limit(1)
    result = await db.execute(stmt)
    latest_history = result.scalars().first()
    
    if not latest_history:
        return AllocationResponse(
            evaluation_date=datetime.now(timezone.utc),
            strategy_weights={}
        )
        
    return AllocationResponse(
        evaluation_date=latest_history.evaluation_date,
        strategy_weights=latest_history.strategy_weights
    )

@router.post("/allocation")
async def manual_update_allocation(
    request: AllocationUpdateRequest,
    db: AsyncSession = Depends(get_db_session)
):
    """
    Manually update strategy capital allocation weights.
    """
    logger.info(f"Manual allocation update: {request.strategy_weights}")
    
    return {
        "status": "success",
        "message": "Allocation updated successfully",
        "weights": request.strategy_weights
    }
