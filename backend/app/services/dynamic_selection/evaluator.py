from datetime import datetime
from app.models.db_models import PerformanceMetric, StrategyEvaluation

class StrategyEvaluator:
    """策略评估器：计算策略的五维雷达图得分"""
    
    @staticmethod
    def calculate_scores(performance: PerformanceMetric) -> dict:
        """
        计算综合得分（0-100分）
        包含：收益能力(30%)、风险控制(25%)、风险调整收益(25%)、稳定性(10%)、交易效率(10%)
        """
        annual_return = float(performance.annualized_return or 0) / 100.0
        max_drawdown = float(performance.max_drawdown_pct or 0) / 100.0
        sharpe_ratio = float(performance.sharpe_ratio or 0)
        win_rate = float(performance.win_rate or 0) / 100.0
        num_trades = int(performance.total_trades or 0)
        
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

    def evaluate(self, strategy_id: str, performance: PerformanceMetric, window_start: datetime, window_end: datetime) -> StrategyEvaluation:
        """评估单个策略表现，生成 StrategyEvaluation 记录"""
        scores = self.calculate_scores(performance)
        
        return StrategyEvaluation(
            strategy_id=strategy_id,
            evaluation_date=datetime.utcnow(),
            window_start=window_start,
            window_end=window_end,
            
            # Base performance
            total_return=float(performance.total_return or 0) / 100.0,
            annual_return=float(performance.annualized_return or 0) / 100.0,
            volatility=float(performance.volatility or 0) / 100.0,
            max_drawdown=float(performance.max_drawdown_pct or 0) / 100.0,
            sharpe_ratio=float(performance.sharpe_ratio or 0),
            sortino_ratio=float(performance.sortino_ratio or 0),
            calmar_ratio=float(performance.calmar_ratio or 0),
            win_rate=float(performance.win_rate or 0) / 100.0,
            num_trades=int(performance.total_trades or 0),
            
            # Scores
            return_score=scores["return_score"],
            risk_score=scores["risk_score"],
            risk_adjusted_score=scores["risk_adjusted_score"],
            stability_score=scores["stability_score"],
            efficiency_score=scores["efficiency_score"],
            total_score=scores["total_score"]
        )
