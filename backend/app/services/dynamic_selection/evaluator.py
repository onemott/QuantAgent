from datetime import datetime, timezone
from typing import Optional
from app.models.db_models import PerformanceMetric, StrategyEvaluation
from app.services.metrics_calculator import StandardizedMetricsSnapshot

class StrategyEvaluator:
    """策略评估器：计算策略的五维雷达图得分"""
    
    @staticmethod
    def _standardize_metrics(performance: PerformanceMetric) -> StandardizedMetricsSnapshot:
        """
        Normalize ORM / VirtualBus-style metrics to the canonical decimal schema.

        Prefer explicit `metric_types` metadata when available.
        Legacy percentage payloads fall back to heuristic normalization.
        """
        return StandardizedMetricsSnapshot.from_source(performance)

    @staticmethod
    def calculate_scores(performance: PerformanceMetric) -> dict:
        """
        计算综合得分（0-100分）
        包含：收益能力(30%)、风险控制(25%)、风险调整收益(25%)、稳定性(10%)、交易效率(10%)
        """
        standardized = StrategyEvaluator._standardize_metrics(performance)
        annual_return = standardized.annualized_return
        max_drawdown = standardized.max_drawdown_pct
        sharpe_ratio = standardized.sharpe_ratio
        win_rate = standardized.win_rate
        num_trades = standardized.total_trades
        
        # 1. 收益能力得分（0-30分）
        # 假设年化收益率20%为满分
        return_score = min(max(annual_return, 0) / 0.2, 1.0) * 30
        
        # 2. 风险控制得分（0-25分）
        # 最大回撤越小越好，最大回撤超过30%为0分
        drawdown_score = max(1 - max_drawdown / 0.3, 0) * 25
        
        # 3. 风险调整收益得分（0-25分）
        # 夏普比率超过2.0为满分
        sharpe_score = min(max(sharpe_ratio, 0) / 2.0, 1.0) * 25
        
        # 4. 稳定性得分（0-10分）
        # 胜率直接作为得分依据
        stability_score = win_rate * 10
        
        # 5. 交易效率得分（0-10分）
        # 避免交易过度或不交易。这里设定基础交易次数限制（10次满分）
        if num_trades >= 10:
            efficiency_score = 10.0
        else:
            efficiency_score = (num_trades / 10.0) * 10.0
            
        total_score = return_score + drawdown_score + sharpe_score + stability_score + efficiency_score
        
        return {
            "return_score": round(return_score, 2),
            "risk_score": round(drawdown_score, 2),
            "risk_adjusted_score": round(sharpe_score, 2),
            "stability_score": round(stability_score, 2),
            "efficiency_score": round(efficiency_score, 2),
            "total_score": round(total_score, 2)
        }

    def evaluate(
        self,
        strategy_id: str,
        performance: PerformanceMetric,
        window_start: datetime,
        window_end: datetime,
        evaluation_date: Optional[datetime] = None
    ) -> StrategyEvaluation:
        """评估单个策略表现，生成 StrategyEvaluation 记录
        
        Args:
            strategy_id: 策略ID
            performance: 性能指标
            window_start: 评估窗口开始时间
            window_end: 评估窗口结束时间
            evaluation_date: 评估时间戳，如果为None则使用当前UTC时间
        """
        standardized = self._standardize_metrics(performance)
        scores = self.calculate_scores(performance)
        
        # 使用传入的 evaluation_date，如果没有则使用当前UTC时间
        eval_date = evaluation_date if evaluation_date is not None else datetime.now(timezone.utc)
        
        return StrategyEvaluation(
            strategy_id=strategy_id,
            evaluation_date=eval_date,
            window_start=window_start,
            window_end=window_end,
            
            # Base performance always uses the canonical decimal type system.
            total_return=standardized.total_return,
            annual_return=standardized.annualized_return,
            volatility=standardized.volatility,
            max_drawdown=standardized.max_drawdown_pct,
            sharpe_ratio=standardized.sharpe_ratio,
            sortino_ratio=standardized.sortino_ratio,
            calmar_ratio=standardized.calmar_ratio,
            win_rate=standardized.win_rate,
            num_trades=standardized.total_trades,
            
            # Scores
            return_score=scores["return_score"],
            risk_score=scores["risk_score"],
            risk_adjusted_score=scores["risk_adjusted_score"],
            stability_score=scores["stability_score"],
            efficiency_score=scores["efficiency_score"],
            total_score=scores["total_score"]
        )
