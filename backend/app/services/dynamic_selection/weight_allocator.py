from typing import List, Dict
from .ranker import RankedStrategy

class WeightAllocator:
    """策略权重分配器：根据保留策略的得分、排名、或风险等信息分配资金权重"""

    def allocate_weights(
        self,
        surviving_strategies: List[RankedStrategy],
        method: str = "rank_based",
        min_weight_floor: float = 0.0,
        max_single_strategy_weight: float = 1.0,
    ) -> Dict[str, float]:
        """
        分配策略权重。
        
        :param surviving_strategies: 淘汰后的存活策略列表
        :param method: 权重分配方法 ("equal", "rank_based", "score_based", "risk_parity")
        :return: 策略权重字典 {strategy_id: weight_ratio} (总和应为1.0)
        """
        if not surviving_strategies:
            return {}

        if min_weight_floor < 0:
            raise ValueError("min_weight_floor must be >= 0")
        if max_single_strategy_weight <= 0:
            raise ValueError("max_single_strategy_weight must be > 0")

        if method == "equal":
            # 等权重分配
            n = len(surviving_strategies)
            weight = round(1.0 / n, 4)
            weights = {s.strategy_id: weight for s in surviving_strategies[:-1]}
            if surviving_strategies:
                weights[surviving_strategies[-1].strategy_id] = round(1.0 - sum(weights.values()), 4)
            return self._apply_weight_constraints(weights, min_weight_floor, max_single_strategy_weight)
            
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

            return self._apply_weight_constraints(weights, min_weight_floor, max_single_strategy_weight)
            
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
                return self._apply_weight_constraints(weights, min_weight_floor, max_single_strategy_weight)
                
            weights = {}
            for s in surviving_strategies[:-1]:
                weights[s.strategy_id] = round(s.score / total_score, 4)
            if surviving_strategies:
                last_s = surviving_strategies[-1]
                weights[last_s.strategy_id] = round(1.0 - sum(weights.values()), 4)
            return self._apply_weight_constraints(weights, min_weight_floor, max_single_strategy_weight)
            
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
            return self._apply_weight_constraints(weights, min_weight_floor, max_single_strategy_weight)
            
        else:
            raise ValueError(f"不支持的权重分配方法: {method}")

    @staticmethod
    def _apply_weight_constraints(
        weights: Dict[str, float],
        min_weight_floor: float,
        max_single_strategy_weight: float,
    ) -> Dict[str, float]:
        if not weights:
            return {}

        strategy_ids = list(weights.keys())
        if min_weight_floor * len(strategy_ids) > 1.0:
            raise ValueError("min_weight_floor is too large for the number of strategies")
        if max_single_strategy_weight < min_weight_floor:
            raise ValueError("max_single_strategy_weight must be >= min_weight_floor")

        if max_single_strategy_weight * len(strategy_ids) < 1.0:
            raise ValueError("max_single_strategy_weight is too small to allocate full capital")

        incoming_total = sum(max(float(weights.get(strategy_id, 0.0)), 0.0) for strategy_id in strategy_ids)
        if incoming_total <= 0:
            normalized_input = {strategy_id: 1.0 / len(strategy_ids) for strategy_id in strategy_ids}
        else:
            normalized_input = {
                strategy_id: max(float(weights.get(strategy_id, 0.0)), 0.0) / incoming_total
                for strategy_id in strategy_ids
            }

        if all(
            min_weight_floor - 1e-12 <= normalized_input[strategy_id] <= max_single_strategy_weight + 1e-12
            for strategy_id in strategy_ids
        ):
            return normalized_input

        constrained = {strategy_id: min_weight_floor for strategy_id in strategy_ids}
        remaining_capacity = 1.0 - min_weight_floor * len(strategy_ids)
        if remaining_capacity <= 0:
            return constrained

        raw_scores = {
            strategy_id: max(normalized_input[strategy_id] - min_weight_floor, 0.0)
            for strategy_id in strategy_ids
        }
        available = {
            strategy_id: max_single_strategy_weight - min_weight_floor
            for strategy_id in strategy_ids
        }
        active_ids = {strategy_id for strategy_id, capacity in available.items() if capacity > 0}

        while remaining_capacity > 1e-12 and active_ids:
            raw_total = sum(raw_scores[strategy_id] for strategy_id in active_ids)
            if raw_total <= 0:
                equal_share = remaining_capacity / len(active_ids)
                for strategy_id in list(active_ids):
                    add_weight = min(equal_share, available[strategy_id])
                    constrained[strategy_id] += add_weight
                    remaining_capacity -= add_weight
                    available[strategy_id] -= add_weight
                    if available[strategy_id] <= 1e-12:
                        active_ids.remove(strategy_id)
                continue

            round_remaining = remaining_capacity
            exhausted_ids = set()
            for strategy_id in list(active_ids):
                proportional_share = round_remaining * (raw_scores[strategy_id] / raw_total)
                add_weight = min(proportional_share, available[strategy_id])
                constrained[strategy_id] += add_weight
                remaining_capacity -= add_weight
                available[strategy_id] -= add_weight
                if available[strategy_id] <= 1e-12:
                    exhausted_ids.add(strategy_id)

            active_ids -= exhausted_ids
            if not exhausted_ids and raw_total > 0:
                # 单轮没有任何策略触碰约束时，认为剩余容量已按比例充分分配。
                break

        total_weight = sum(constrained.values())
        if total_weight <= 0:
            equal_weight = 1.0 / len(strategy_ids)
            return {strategy_id: equal_weight for strategy_id in strategy_ids}

        normalized = {
            strategy_id: constrained[strategy_id] / total_weight
            for strategy_id in strategy_ids
        }
        return normalized
