from dataclasses import dataclass
from typing import List, Dict, Optional
from app.models.db_models import StrategyEvaluation

@dataclass
class RankedStrategy:
    strategy_id: str
    score: float
    rank: int
    evaluation: StrategyEvaluation

class StrategyRanker:
    """策略排名器：根据综合得分进行策略排名"""

    def rank_evaluations(self, evaluations: List[StrategyEvaluation], historical_weights: Optional[Dict[str, float]] = None) -> List[RankedStrategy]:
        """
        对一批策略的评估结果进行排名，支持历史权重调整。
        
        :param evaluations: 本期所有策略的 StrategyEvaluation 列表
        :param historical_weights: 策略的过往历史表现加权字典 {strategy_id: weight} (通常介于 0.0 ~ 1.0)
        """
        historical_weights = historical_weights or {}
        results = []
        
        for eval_record in evaluations:
            # 基础得分
            base_score = eval_record.total_score or 0.0
            
            # 添加历史加权（如果有）
            # 假定历史加权占30%，当期占70%。若无历史记录则全看当期。
            hw = historical_weights.get(eval_record.strategy_id)
            if hw is not None:
                # 假设历史 weight 最大为1.0，放大到100分制
                final_score = base_score * 0.7 + (hw * 100) * 0.3
            else:
                final_score = base_score
                
            results.append(RankedStrategy(
                strategy_id=eval_record.strategy_id,
                score=final_score,
                rank=0,
                evaluation=eval_record
            ))
            
        # 按照最终得分倒序排序
        results.sort(key=lambda x: x.score, reverse=True)
        
        # 分配排名并更新到原始 evaluation 对象
        total_strategies = len(results)
        for i, rs in enumerate(results):
            rs.rank = i + 1
            rs.evaluation.rank = rs.rank
            rs.evaluation.total_strategies = total_strategies
            
        return results
