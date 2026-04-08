from typing import List, Dict
from .ranker import RankedStrategy

class WeightAllocator:
    """策略权重分配器：根据保留策略的得分、排名、或风险等信息分配资金权重"""

    def allocate_weights(
        self,
        surviving_strategies: List[RankedStrategy],
        method: str = "rank_based"
    ) -> Dict[str, float]:
        """
        分配策略权重。
        
        :param surviving_strategies: 淘汰后的存活策略列表
        :param method: 权重分配方法 ("equal", "rank_based", "score_based", "risk_parity")
        :return: 策略权重字典 {strategy_id: weight_ratio} (总和应为1.0)
        """
        if not surviving_strategies:
            return {}
            
        if method == "equal":
            # 等权重分配
            n = len(surviving_strategies)
            weight = round(1.0 / n, 4)
            weights = {s.strategy_id: weight for s in surviving_strategies[:-1]}
            if surviving_strategies:
                weights[surviving_strategies[-1].strategy_id] = round(1.0 - sum(weights.values()), 4)
            return weights
            
        elif method == "rank_based":
            # 基于排名的线性权重分配（排名越高，权重越大）
            n = len(surviving_strategies)
            total_rank_sum = n * (n + 1) / 2
            
            weights = {}
            for index, s in enumerate(surviving_strategies[:-1]):
                # 如果 rank 未被正确赋予，则用在列表中的索引替代（因为已按得分降序排列）
                rank = s.rank if s.rank > 0 else (index + 1)
                rank_weight = (n - rank + 1) / total_rank_sum
                weights[s.strategy_id] = round(rank_weight, 4)
                
            if surviving_strategies:
                last_s = surviving_strategies[-1]
                weights[last_s.strategy_id] = round(1.0 - sum(weights.values()), 4)
                
            return weights
            
        elif method == "score_based":
            # 基于评估总分的权重分配
            total_score = sum(s.score for s in surviving_strategies)
            if total_score <= 0:
                # 分数全部为0时降级为等权重
                n = len(surviving_strategies)
                weight = round(1.0 / n, 4)
                weights = {s.strategy_id: weight for s in surviving_strategies[:-1]}
                if surviving_strategies:
                    weights[surviving_strategies[-1].strategy_id] = round(1.0 - sum(weights.values()), 4)
                return weights
                
            weights = {}
            for s in surviving_strategies[:-1]:
                weights[s.strategy_id] = round(s.score / total_score, 4)
            if surviving_strategies:
                last_s = surviving_strategies[-1]
                weights[last_s.strategy_id] = round(1.0 - sum(weights.values()), 4)
            return weights
            
        elif method == "risk_parity":
            # 风险平价权重分配（基于年化波动率的反比）
            volatilities = {}
            for s in surviving_strategies:
                # 优先获取波动率，若不存在或为0则默认赋予一个极小值避免除零异常
                vol = float(s.evaluation.volatility or 0.0)
                if vol <= 0:
                    vol = 0.01
                volatilities[s.strategy_id] = vol
                
            total_inv_vol = sum(1.0 / v for v in volatilities.values())
            
            weights = {}
            for s in surviving_strategies[:-1]:
                vol = volatilities[s.strategy_id]
                weights[s.strategy_id] = round((1.0 / vol) / total_inv_vol, 4)
                
            if surviving_strategies:
                last_s = surviving_strategies[-1]
                weights[last_s.strategy_id] = round(1.0 - sum(weights.values()), 4)
            return weights
            
        else:
            raise ValueError(f"不支持的权重分配方法: {method}")
