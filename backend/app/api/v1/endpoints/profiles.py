"""
策略配置方案 (Strategy Profiles) 端点
提供预设策略配置方案的查询和回测功能
"""

import logging
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query

from app.services.database import get_db
from app.models.db_models import BacktestResult, PerformanceMetric
from sqlalchemy import select, func

logger = logging.getLogger(__name__)
router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# 风险等级映射
# ─────────────────────────────────────────────────────────────────────────────

RISK_LEVEL_NAMES = {
    "conservative": "保守型",
    "moderate": "稳健型",
    "balanced": "平衡型",
    "aggressive": "激进型",
    "ultra_aggressive": "超激进型",
}

RISK_LEVEL_COLORS = {
    "conservative": "#22c55e",      # 绿色
    "moderate": "#3b82f6",         # 蓝色
    "balanced": "#eab308",         # 黄色
    "aggressive": "#f97316",       # 橙色
    "ultra_aggressive": "#ef4444", # 红色
}

STRATEGY_TYPE_NAMES = {
    "ema_triple": "三线EMA策略",
    "atr_trend": "ATR趋势策略",
    "turtle": "海龟策略",
    "ichimoku": "一目均衡表策略",
}


# ─────────────────────────────────────────────────────────────────────────────
# 请求/响应模型
# ─────────────────────────────────────────────────────────────────────────────

class ProfileParams:
    """策略配置方案参数"""
    def __init__(self, params: dict):
        self.data = params
        self.formatted = self._format()
    
    def _format(self) -> dict:
        """格式化参数显示"""
        result = {}
        for key, value in self.data.items():
            if isinstance(value, float):
                result[key] = f"{value:.2f}"
            else:
                result[key] = str(value)
        return result
    
    def to_display(self) -> List[dict]:
        """转换为前端显示格式"""
        labels = {
            # EMA
            "fast_period": "快线周期",
            "mid_period": "中线周期",
            "slow_period": "慢线周期",
            # ATR
            "atr_period": "ATR周期",
            "atr_multiplier": "ATR倍数",
            "trend_period": "趋势周期",
            # Turtle
            "entry_period": "入场周期",
            "exit_period": "出场周期",
            # Ichimoku
            "tenkan_period": "转换线周期",
            "kijun_period": "基准线周期",
            "senkou_b_period": "先行带B周期",
        }
        return [
            {"key": key, "label": labels.get(key, key), "value": value}
            for key, value in self.data.items()
        ]


class StrategyProfileResponse:
    """策略配置方案响应"""
    def __init__(self, row: BacktestResult):
        self.id = row.id
        self.strategy_type = row.strategy_type
        self.strategy_type_name = STRATEGY_TYPE_NAMES.get(row.strategy_type, row.strategy_type)
        self.symbol = row.symbol
        self.interval = row.interval
        self.params = row.params
        self.params_display = ProfileParams(row.params).to_display()
        self.metrics = row.metrics
        self.created_at = row.created_at.isoformat() if row.created_at else None
        
        # 解析风险等级
        self.risk_level = row.metrics.get("risk_level", "balanced")
        self.risk_level_name = RISK_LEVEL_NAMES.get(self.risk_level, self.risk_level)
        self.risk_level_color = RISK_LEVEL_COLORS.get(self.risk_level, "#888888")
        
        # 解析方案ID
        self.profile_id = row.metrics.get("profile_id", f"{self.strategy_type}_{self.id}")
        
        # 解析性能指标
        self.total_return = row.metrics.get("total_return", 0)
        self.annual_return = row.metrics.get("annual_return", 0)
        self.max_drawdown = row.metrics.get("max_drawdown", 0)
        self.sharpe_ratio = row.metrics.get("sharpe_ratio", 0)
        self.win_rate = row.metrics.get("win_rate", 0)
        self.profit_factor = row.metrics.get("profit_factor", 0)
        self.total_trades = row.metrics.get("total_trades", 0)
        self.initial_capital = row.metrics.get("initial_capital", 0)
        self.final_capital = row.metrics.get("final_capital", 0)
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "profile_id": self.profile_id,
            "strategy_type": self.strategy_type,
            "strategy_type_name": self.strategy_type_name,
            "symbol": self.symbol,
            "interval": self.interval,
            "params": self.params,
            "params_display": self.params_display,
            "metrics": self.metrics,
            "risk_level": self.risk_level,
            "risk_level_name": self.risk_level_name,
            "risk_level_color": self.risk_level_color,
            "total_return": self.total_return,
            "annual_return": self.annual_return,
            "max_drawdown": self.max_drawdown,
            "sharpe_ratio": self.sharpe_ratio,
            "win_rate": self.win_rate,
            "profit_factor": self.profit_factor,
            "total_trades": self.total_trades,
            "initial_capital": self.initial_capital,
            "final_capital": self.final_capital,
            "created_at": self.created_at,
        }


# ─────────────────────────────────────────────────────────────────────────────
# API 端点
# ─────────────────────────────────────────────────────────────────────────────

@router.get("")
async def get_strategy_profiles(
    risk_level: Optional[str] = Query(None, description="风险等级筛选"),
    strategy_type: Optional[str] = Query(None, description="策略类型筛选"),
    limit: int = Query(50, ge=1, le=100, description="返回数量"),
) -> dict:
    """
    获取策略配置方案列表
    
    返回所有预设的策略配置方案，按风险等级分组。
    每个方案包含策略参数和回测性能指标。
    """
    async with get_db() as session:
        # 构建查询
        stmt = select(BacktestResult)
        
        # 筛选条件：只返回有profile_id的记录（模拟数据）
        stmt = stmt.where(BacktestResult.metrics.op("->>")("profile_id").isnot(None))
        
        if risk_level:
            stmt = stmt.where(BacktestResult.metrics.op("->>")("risk_level") == risk_level)
        
        if strategy_type:
            stmt = stmt.where(BacktestResult.strategy_type == strategy_type)
        
        # 按风险等级和策略类型排序
        stmt = stmt.order_by(
            BacktestResult.metrics.op("->>")("risk_level").asc(),
            BacktestResult.strategy_type.asc(),
            BacktestResult.created_at.desc()
        ).limit(limit)
        
        result = await session.execute(stmt)
        rows = result.scalars().all()
    
    # 转换为响应格式
    profiles = [StrategyProfileResponse(row).to_dict() for row in rows]
    
    # 按风险等级分组
    grouped = {}
    for profile in profiles:
        level = profile["risk_level"]
        if level not in grouped:
            grouped[level] = {
                "risk_level": level,
                "risk_level_name": profile["risk_level_name"],
                "risk_level_color": profile["risk_level_color"],
                "profiles": []
            }
        grouped[level]["profiles"].append(profile)
    
    return {
        "profiles": profiles,
        "grouped": list(grouped.values()),
        "total": len(profiles),
        "risk_levels": [
            {"value": k, "label": v, "color": RISK_LEVEL_COLORS.get(k, "#888888")}
            for k, v in RISK_LEVEL_NAMES.items()
        ],
        "strategy_types": [
            {"value": k, "label": v}
            for k, v in STRATEGY_TYPE_NAMES.items()
        ],
    }


@router.get("/profiles/{profile_id}")
async def get_strategy_profile(profile_id: str) -> dict:
    """
    获取指定策略配置方案的详细信息
    """
    async with get_db() as session:
        stmt = select(BacktestResult).where(
            BacktestResult.metrics.op("->>")("profile_id") == profile_id
        ).limit(1)
        
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
    
    if not row:
        raise HTTPException(status_code=404, detail=f"策略配置方案 '{profile_id}' 不存在")
    
    return StrategyProfileResponse(row).to_dict()


@router.get("/compare")
async def compare_profiles(
    profile_ids: str = Query(..., description="要对比的方案ID，逗号分隔")
) -> dict:
    """
    对比多个策略配置方案
    """
    ids = [id.strip() for id in profile_ids.split(",")]
    
    async with get_db() as session:
        conditions = [BacktestResult.metrics.op("->>")("profile_id") == id for id in ids]
        stmt = select(BacktestResult).where(
            or_(*conditions) if len(conditions) > 1 else conditions[0]
        )
        
        result = await session.execute(stmt)
        rows = result.scalars().all()
    
    profiles = [StrategyProfileResponse(row).to_dict() for row in rows]
    
    # 计算对比统计
    if profiles:
        best_return = max(profiles, key=lambda x: x["total_return"])
        lowest_dd = min(profiles, key=lambda x: x["max_drawdown"])
        best_sharpe = max(profiles, key=lambda x: x["sharpe_ratio"])
        
        return {
            "profiles": profiles,
            "comparison": {
                "best_return": {"profile_id": best_return["profile_id"], "value": best_return["total_return"]},
                "lowest_drawdown": {"profile_id": lowest_dd["profile_id"], "value": lowest_dd["max_drawdown"]},
                "best_sharpe": {"profile_id": best_sharpe["profile_id"], "value": best_sharpe["sharpe_ratio"]},
            }
        }
    
    return {"profiles": [], "comparison": {}}


# ─────────────────────────────────────────────────────────────────────────────
# 辅助函数
# ─────────────────────────────────────────────────────────────────────────────

from sqlalchemy import or_

# 重命名以避免与策略类型冲突
__all__ = ["router", "RISK_LEVEL_NAMES", "RISK_LEVEL_COLORS", "STRATEGY_TYPE_NAMES"]
