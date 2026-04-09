"""
Dynamic Strategy Selection Endpoints
Provides endpoints for strategy evaluation, dynamic selection configuration,
radar metrics, and allocation tracking.
"""

import json
import logging
import numpy as np
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
from typing import List, Dict, Any, Optional, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func as sql_func
from pydantic import BaseModel, Field, field_validator

from app.services.database import get_db_session
from app.models.db_models import (
    StrategyEvaluation, SelectionHistory, TradePair, PerformanceMetric
)
from app.services.dynamic_selection import (
    StrategyEvaluator, StrategyRanker, StrategyEliminator, EliminationRule, WeightAllocator
)

logger = logging.getLogger(__name__)
router = APIRouter()

# ─────────────────────────────────────────────────────────────────────────────
# Helper Functions for Strategy Display
# ─────────────────────────────────────────────────────────────────────────────

# 颜色调色板常量
_COLOR_PALETTE = [
    "#3b82f6", "#8b5cf6", "#10b981", "#06b6d4",
    "#f43f5e", "#f59e0b", "#ec4899", "#6366f1"
]

# 策略ID到可读名称的映射
_STRATEGY_DISPLAY_NAMES = {
    "ma": "双均线 (MA)",
    "rsi": "RSI 振荡器",
    "boll": "布林带 (BOLL)",
    "macd": "MACD 信号",
    "atr": "ATR 趋势",
}


def _get_strategy_display_name(strategy_id: str) -> str:
    """
    将策略ID转换为可读的显示名称。
    
    Args:
        strategy_id: 原始策略ID（如 'ma', 'rsi', 'strategy_ma' 等）
        
    Returns:
        可读的策略名称（如 '双均线 (MA)', 'RSI 振荡器' 等）
    """
    # 处理 strategy_ 前缀
    if strategy_id.startswith("strategy_"):
        return strategy_id.replace("strategy_", "").upper()
    
    # 检查已知策略前缀
    for prefix, display_name in _STRATEGY_DISPLAY_NAMES.items():
        if strategy_id.startswith(prefix):
            return display_name
    
    # 默认返回大写的原始ID
    return strategy_id.upper()


def _get_strategy_color(index: int) -> str:
    """
    获取策略对应的颜色。
    
    Args:
        index: 策略在列表中的索引位置
        
    Returns:
        十六进制颜色代码
    """
    return _COLOR_PALETTE[index % len(_COLOR_PALETTE)]

# ─────────────────────────────────────────────────────────────────────────────
# Request / Response Models
# ─────────────────────────────────────────────────────────────────────────────

class DynamicSelectionConfig(BaseModel):
    """动态策略选择配置模型，包含参数范围验证"""
    evaluation_period: Literal["1d", "1w", "1m"] = Field(
        default="1w", 
        description="评估周期: 1d=每日, 1w=每周, 1m=每月"
    )
    elimination_threshold: int = Field(
        default=40, 
        ge=0, 
        le=100,
        description="淘汰阈值(0-100分): 低于此分数的策略将被淘汰"
    )
    relative_ratio: float = Field(
        default=0.2, 
        ge=0.0, 
        le=1.0,
        description="相对淘汰比例(0-1): 末位淘汰的比例"
    )
    min_strategies: int = Field(
        default=3, 
        ge=1, 
        le=10,
        description="最少保留策略数(1-10): 淘汰后至少保留的策略数量"
    )
    max_strategies: int = Field(
        default=10, 
        ge=1, 
        le=20,
        description="最多活跃策略数(1-20)"
    )
    metrics_weights: Dict[str, float] = Field(
        default={
            "return_score": 0.3,
            "risk_score": 0.3,
            "stability_score": 0.2,
            "efficiency_score": 0.2
        }, 
        description="评估指标权重"
    )
    
    @field_validator('metrics_weights')
    @classmethod
    def validate_weights_sum(cls, v: Dict[str, float]) -> Dict[str, float]:
        """验证权重总和是否为1"""
        total = sum(v.values())
        if abs(total - 1.0) > 0.01:
            raise ValueError(f'权重总和必须为1.0，当前为 {total:.2f}')
        return v
    
    @field_validator('max_strategies')
    @classmethod
    def validate_max_ge_min(cls, v: int, info) -> int:
        """验证 max_strategies >= min_strategies"""
        min_strategies = info.data.get('min_strategies', 3)
        if v < min_strategies:
            raise ValueError(f'max_strategies({v}) 必须大于等于 min_strategies({min_strategies})')
        return v

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

class StatusResponse(BaseModel):
    """Response model for the status endpoint - matches frontend MonitorData interface"""
    dimensions: List[Dict[str, Any]] = Field(default=[], description="策略维度评分数据")
    weights: List[Dict[str, Any]] = Field(default=[], description="策略权重分配数据")
    lastUpdated: str = Field(default="", description="最后评估时间（ISO字符串）")
    activeCount: int = Field(default=0, description="当前活跃策略数量")
    totalAllocation: int = Field(default=100000, description="总分配资金（USDT）")

# ─────────────────────────────────────────────────────────────────────────────
# Configuration Persistence (JSON file based)
# ─────────────────────────────────────────────────────────────────────────────

# 配置文件路径：backend/config/dynamic_selection_config.json
_CONFIG_DIR = Path(__file__).parent.parent.parent.parent / "config"
_CONFIG_FILE = _CONFIG_DIR / "dynamic_selection_config.json"


def _load_config_from_file() -> DynamicSelectionConfig:
    """
    从 JSON 文件加载配置，如果文件不存在则返回默认配置。
    """
    try:
        if _CONFIG_FILE.exists():
            with open(_CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return DynamicSelectionConfig(**data)
    except Exception as e:
        logger.warning(f"Failed to load config from file: {e}, using default config")
    return DynamicSelectionConfig()


def _save_config_to_file(config: DynamicSelectionConfig) -> bool:
    """
    将配置保存到 JSON 文件。
    
    Returns:
        True if saved successfully, False otherwise
    """
    try:
        # 确保目录存在
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        
        with open(_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config.model_dump(), f, indent=2, ensure_ascii=False)
        logger.info(f"Config saved to {_CONFIG_FILE}")
        return True
    except Exception as e:
        logger.error(f"Failed to save config to file: {e}")
        return False


# 启动时从文件加载配置，如果文件不存在则使用默认值
_current_config = _load_config_from_file()

# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/config", response_model=DynamicSelectionConfig)
async def get_config():
    """Get current dynamic selection configuration."""
    return _current_config

@router.post("/config", response_model=DynamicSelectionConfig)
async def update_config(config: DynamicSelectionConfig):
    """
    Update dynamic selection configuration.
    配置将持久化到 JSON 文件，服务重启后保留。
    """
    global _current_config
    _current_config = config
    
    # 持久化到文件
    if _save_config_to_file(config):
        logger.info(f"Dynamic selection config updated and saved: {config.model_dump()}")
    else:
        logger.warning("Config updated in memory but failed to save to file")
    
    return _current_config

# ─────────────────────────────────────────────────────────────────────────────
# Helper Functions for Performance Calculation
# ─────────────────────────────────────────────────────────────────────────────

async def _get_strategy_performance(
    db: AsyncSession,
    strategy_id: str,
    window_start: datetime,
    window_end: datetime
) -> Optional[PerformanceMetric]:
    """
    从 TradePair 表按策略计算性能指标，构造 PerformanceMetric 对象用于评估。
    
    Args:
        db: 数据库会话
        strategy_id: 策略ID
        window_start: 评估窗口开始时间
        window_end: 评估窗口结束时间
    
    Returns:
        PerformanceMetric 对象（不存入数据库），或 None 如果无交易数据
    """
    # 查询该策略在时间窗口内的所有已关闭交易对
    stmt = (
        select(TradePair)
        .where(TradePair.strategy_id == strategy_id)
        .where(TradePair.status == "CLOSED")
        .where(TradePair.exit_time >= window_start)
        .where(TradePair.exit_time <= window_end)
        .order_by(TradePair.exit_time.asc())
    )
    result = await db.execute(stmt)
    pairs = result.scalars().all()
    
    if not pairs:
        logger.warning(f"No closed trades found for strategy {strategy_id} in window")
        return None
    
    # 计算基础指标
    total_trades = len(pairs)
    pnls = [float(p.pnl) for p in pairs if p.pnl is not None]
    pnl_pcts = [float(p.pnl_pct) for p in pairs if p.pnl_pct is not None]
    
    if not pnls:
        return None
    
    total_pnl = sum(pnls)
    winning_trades = len([p for p in pnls if p > 0])
    losing_trades = len([p for p in pnls if p < 0])
    
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
    
    # 计算总收益
    total_return = sum(pnl_pcts) if pnl_pcts else 0
    
    # 计算最大回撤
    cumulative_pnl = 0.0
    peak = 0.0
    max_drawdown = 0.0
    max_drawdown_pct = 0.0
    
    for pnl in pnls:
        cumulative_pnl += pnl
        if cumulative_pnl > peak:
            peak = cumulative_pnl
        dd = peak - cumulative_pnl
        if dd > max_drawdown:
            max_drawdown = dd
            # 使用初始资金估算回撤百分比
            max_drawdown_pct = (dd / 100000) * 100 if peak > 0 else 0
    
    # 计算夏普比率（简化版本：基于交易收益）
    if len(pnl_pcts) >= 5:
        returns_std = np.std(pnl_pcts)
        avg_return = np.mean(pnl_pcts)
        # 年化（假设每天1笔交易）
        annualized_return = avg_return * 252
        annualized_vol = returns_std * np.sqrt(252)
        sharpe_ratio = (annualized_return - 3.0) / annualized_vol if annualized_vol > 0 else 0
    else:
        sharpe_ratio = 0
        annualized_return = total_return * (365 / max((window_end - window_start).days, 1))
    
    # 构造 PerformanceMetric 对象
    return PerformanceMetric(
        period="custom",
        start_date=window_start,
        end_date=window_end,
        initial_equity=Decimal("100000"),
        final_equity=Decimal(str(100000 + total_pnl)),
        total_return=Decimal(str(total_return)),
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        max_drawdown=Decimal(str(max_drawdown)),
        max_drawdown_pct=Decimal(str(max_drawdown_pct)),
        volatility=Decimal("0"),  # 简化处理
        annualized_return=Decimal(str(annualized_return)),
        sharpe_ratio=Decimal(str(sharpe_ratio)) if sharpe_ratio else None,
        win_rate=Decimal(str(win_rate)),
    )


async def _get_all_strategies_with_trades(
    db: AsyncSession,
    window_start: datetime,
    window_end: datetime
) -> List[str]:
    """
    获取在指定时间窗口内有交易的所有策略ID列表。
    """
    stmt = (
        select(TradePair.strategy_id)
        .where(TradePair.status == "CLOSED")
        .where(TradePair.exit_time >= window_start)
        .where(TradePair.exit_time <= window_end)
        .where(TradePair.strategy_id.isnot(None))
        .distinct()
    )
    result = await db.execute(stmt)
    return [row[0] for row in result.all()]


# ─────────────────────────────────────────────────────────────────────────────
# Evaluation Endpoint
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/evaluate")
async def trigger_evaluation(
    request: EvaluateRequest,
    db: AsyncSession = Depends(get_db_session)
):
    """
    执行完整的策略评估流程：
    1. 获取所有有交易的策略
    2. 为每个策略计算性能指标并评估得分
    3. 排名、淘汰、权重分配
    4. 保存评估结果到数据库
    """
    logger.info(f"Starting strategy evaluation from {request.window_start} to {request.window_end}")
    
    # 统一时间戳：用于 StrategyEvaluation 和 SelectionHistory 的 evaluation_date
    evaluation_time = datetime.now(timezone.utc)
    evaluation_start = evaluation_time
    
    try:
        # 初始化组件
        evaluator = StrategyEvaluator()
        ranker = StrategyRanker()
        eliminator = StrategyEliminator()
        allocator = WeightAllocator()
        
        # 1. 获取所有有交易的策略
        strategy_ids = await _get_all_strategies_with_trades(
            db, request.window_start, request.window_end
        )
        
        if not strategy_ids:
            logger.warning("No strategies with trades found in the specified window")
            return {
                "status": "warning",
                "message": "No strategies with closed trades found in the specified time window",
                "window_start": request.window_start,
                "window_end": request.window_end,
                "total_strategies": 0,
                "surviving_count": 0,
                "eliminated_count": 0,
                "evaluation_time_ms": 0
            }
        
        logger.info(f"Found {len(strategy_ids)} strategies with trades: {strategy_ids}")
        
        # 2. 为每个策略计算性能并评估
        evaluations = []
        for strategy_id in strategy_ids:
            try:
                perf_metric = await _get_strategy_performance(
                    db, strategy_id, request.window_start, request.window_end
                )
                
                if perf_metric:
                    evaluation = evaluator.evaluate(
                        strategy_id=strategy_id,
                        performance=perf_metric,
                        window_start=request.window_start,
                        window_end=request.window_end,
                        evaluation_date=evaluation_time
                    )
                    evaluations.append(evaluation)
                    logger.debug(f"Strategy {strategy_id}: total_score={evaluation.total_score}")
            except Exception as e:
                logger.error(f"Error evaluating strategy {strategy_id}: {e}")
                continue
        
        if not evaluations:
            logger.warning("No valid evaluations generated")
            return {
                "status": "warning",
                "message": "No valid strategy evaluations could be generated",
                "window_start": request.window_start,
                "window_end": request.window_end,
                "total_strategies": len(strategy_ids),
                "surviving_count": 0,
                "eliminated_count": 0,
                "evaluation_time_ms": 0
            }
        
        # 3. 排名
        ranked_strategies = ranker.rank_evaluations(evaluations)
        logger.info(f"Ranked {len(ranked_strategies)} strategies")
        
        # 4. 淘汰（使用默认规则）
        elimination_rule = EliminationRule(
            min_score_threshold=40.0,  # 绝对阈值：40分以下淘汰
            elimination_ratio=0.2,      # 相对比例：末位20%淘汰
            min_strategies=3            # 最少保留3个策略
        )
        
        # TODO: 可以从连续低分记录表中获取历史低分次数
        consecutive_low_counts = {}
        
        surviving, eliminated, reasons = eliminator.apply_elimination(
            ranked_strategies,
            elimination_rule,
            consecutive_low_counts
        )
        
        logger.info(f"Elimination result: {len(surviving)} surviving, {len(eliminated)} eliminated")
        
        # 5. 权重分配
        weights = allocator.allocate_weights(surviving, method="score_based")
        logger.info(f"Allocated weights: {weights}")
        
        # 6. 保存评估结果到 StrategyEvaluation 表
        for eval_record in evaluations:
            db.add(eval_record)
        
        # 7. 保存选择历史到 SelectionHistory 表
        # 使用统一的 evaluation_time，确保与 StrategyEvaluation 的 evaluation_date 一致
        history = SelectionHistory(
            evaluation_date=evaluation_time,
            total_strategies=len(ranked_strategies),
            surviving_count=len(surviving),
            eliminated_count=len(eliminated),
            eliminated_strategy_ids=[s.strategy_id for s in eliminated],
            elimination_reasons=reasons,
            strategy_weights=weights,
        )
        db.add(history)
        
        await db.commit()
        logger.info("Evaluation results saved to database")
        
        # 计算评估耗时
        evaluation_time_ms = int((datetime.now(timezone.utc) - evaluation_start).total_seconds() * 1000)
        
        return {
            "status": "success",
            "message": f"Evaluation completed successfully. {len(surviving)} strategies active, {len(eliminated)} eliminated.",
            "window_start": request.window_start,
            "window_end": request.window_end,
            "total_strategies": len(ranked_strategies),
            "surviving_count": len(surviving),
            "eliminated_count": len(eliminated),
            "evaluation_time_ms": evaluation_time_ms,
            "weights": weights,
            "top_strategy": {
                "id": surviving[0].strategy_id,
                "score": round(surviving[0].score, 2),
                "rank": surviving[0].rank
            } if surviving else None
        }
        
    except Exception as e:
        logger.error(f"Evaluation failed: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Evaluation process failed: {str(e)}"
        )

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


@router.get("/status", response_model=StatusResponse)
async def get_status(db: AsyncSession = Depends(get_db_session)):
    """
    Get aggregated status data for the strategy monitor dashboard.
    Returns dimension scores, weights allocation, and summary statistics.
    
    数据一致性保证：
    - 先从 SelectionHistory 获取最新的 evaluation_date 和权重
    - 用同一个 evaluation_date 查询 StrategyEvaluation 表的 dimensions
    - 确保两组数据来自同一次评估
    """
    try:
        dimensions = []
        active_count = 0
        weights = []
        total_allocation = 100000  # 默认总资金
        latest_date = None
        
        # 步骤1：先从 SelectionHistory 获取最新记录（包含 evaluation_date 和 strategy_weights）
        # 这确保了数据来源的一致性
        stmt_history = select(SelectionHistory).order_by(
            desc(SelectionHistory.evaluation_date)
        ).limit(1)
        result_history = await db.execute(stmt_history)
        latest_history = result_history.scalars().first()
        
        if latest_history:
            # 使用 SelectionHistory 的 evaluation_date 作为统一的时间基准
            latest_date = latest_history.evaluation_date
            
            # 步骤2：用同一个 evaluation_date 查询 StrategyEvaluation 表的 dimensions
            stmt_evaluations = select(StrategyEvaluation).where(
                StrategyEvaluation.evaluation_date == latest_date
            ).order_by(desc(StrategyEvaluation.total_score))
            result_evals = await db.execute(stmt_evaluations)
            evaluations = result_evals.scalars().all()
            
            active_count = len(evaluations)
            
            # 构建维度评分数据 - 每个策略作为一个维度
            for idx, eval_record in enumerate(evaluations):
                # 将策略ID转换为可读名称
                strategy_name = _get_strategy_display_name(eval_record.strategy_id)
                
                dimensions.append({
                    "subject": strategy_name,
                    "score": round(eval_record.total_score or 0, 1),
                    "fullMark": 100,
                    "return_score": round(eval_record.return_score or 0, 1),
                    "risk_score": round(eval_record.risk_score or 0, 1),
                    "stability_score": round(eval_record.stability_score or 0, 1),
                    "efficiency_score": round(eval_record.efficiency_score or 0, 1),
                    "risk_adjusted_score": round(eval_record.risk_adjusted_score or 0, 1),
                    "fill": _get_strategy_color(idx)
                })
            
            # 步骤3：从同一个 SelectionHistory 记录获取权重
            if latest_history.strategy_weights:
                strategy_weights = latest_history.strategy_weights
                
                for idx, (strategy_id, weight_value) in enumerate(strategy_weights.items()):
                    # 转换策略ID为可读名称
                    name = _get_strategy_display_name(strategy_id)
                    
                    weights.append({
                        "name": name,
                        "value": round(weight_value * 100, 1),  # 转换为百分比
                        "fill": _get_strategy_color(idx)
                    })
        
        # 如果没有数据，返回默认空结构
        if not dimensions:
            dimensions = [
                {"subject": "动量 (Momentum)", "score": 0, "fullMark": 100},
                {"subject": "均值回归 (Reversion)", "score": 0, "fullMark": 100},
                {"subject": "波动率 (Volatility)", "score": 0, "fullMark": 100},
                {"subject": "成交量 (Volume)", "score": 0, "fullMark": 100},
                {"subject": "市场情绪 (Sentiment)", "score": 0, "fullMark": 100},
            ]
        
        if not weights:
            weights = [
                {"name": "双均线 (MA)", "value": 0, "fill": "#3b82f6"},
                {"name": "RSI 振荡器", "value": 0, "fill": "#8b5cf6"},
                {"name": "MACD 信号", "value": 0, "fill": "#10b981"},
                {"name": "布林带 (BOLL)", "value": 0, "fill": "#06b6d4"},
                {"name": "ATR 趋势", "value": 0, "fill": "#f43f5e"},
            ]
        
        last_updated = latest_date.isoformat() if latest_date else datetime.now(timezone.utc).isoformat()
        
        return StatusResponse(
            dimensions=dimensions,
            weights=weights,
            lastUpdated=last_updated,
            activeCount=active_count,
            totalAllocation=total_allocation
        )
        
    except Exception as e:
        logger.error(f"Error fetching status: {e}")
        # 返回默认空结构而非报错
        return StatusResponse(
            dimensions=[
                {"subject": "动量 (Momentum)", "score": 0, "fullMark": 100},
                {"subject": "均值回归 (Reversion)", "score": 0, "fullMark": 100},
                {"subject": "波动率 (Volatility)", "score": 0, "fullMark": 100},
                {"subject": "成交量 (Volume)", "score": 0, "fullMark": 100},
                {"subject": "市场情绪 (Sentiment)", "score": 0, "fullMark": 100},
            ],
            weights=[
                {"name": "双均线 (MA)", "value": 0, "fill": "#3b82f6"},
                {"name": "RSI 振荡器", "value": 0, "fill": "#8b5cf6"},
                {"name": "MACD 信号", "value": 0, "fill": "#10b981"},
                {"name": "布林带 (BOLL)", "value": 0, "fill": "#06b6d4"},
                {"name": "ATR 趋势", "value": 0, "fill": "#f43f5e"},
            ],
            lastUpdated=datetime.now(timezone.utc).isoformat(),
            activeCount=0,
            totalAllocation=100000
        )
