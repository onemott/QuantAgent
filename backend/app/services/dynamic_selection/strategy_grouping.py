from typing import Dict, List, Tuple

from .ranker import RankedStrategy
from .weight_allocator import WeightAllocator


TREND_STRATEGIES = ["ma", "macd", "ema_triple", "atr_trend", "turtle", "ichimoku"]
OSCILLATOR_STRATEGIES = ["rsi", "boll"]


class StrategyGrouping:
    def get_strategy_group(self, strategy_id: str) -> str:
        if strategy_id in TREND_STRATEGIES:
            return "trend"
        if strategy_id in OSCILLATOR_STRATEGIES:
            return "oscillator"
        return "other"

    def build_strategy_groups(self, strategy_ids: List[str]) -> Dict[str, List[str]]:
        groups: Dict[str, List[str]] = {}
        for strategy_id in strategy_ids:
            group = self.get_strategy_group(strategy_id)
            groups.setdefault(group, []).append(strategy_id)
        return groups

    def get_group_target_weights(self, market_state: str) -> Dict[str, float]:
        if market_state in {"trend_up", "trend_down"}:
            return {"trend": 0.7, "oscillator": 0.3}
        if market_state == "range":
            return {"trend": 0.4, "oscillator": 0.6}
        if market_state == "high_vol":
            return {"trend": 0.5, "oscillator": 0.5}
        return {"trend": 0.5, "oscillator": 0.5}

    def allocate_grouped_weights(
        self,
        ranked_strategies: List[RankedStrategy],
        market_state: str,
        allocator: WeightAllocator,
        method: str = "score_based",
    ) -> Tuple[Dict[str, float], Dict[str, float]]:
        if not ranked_strategies:
            return {}, {}

        grouped_rankings: Dict[str, List[RankedStrategy]] = {}
        for ranked_strategy in ranked_strategies:
            group = self.get_strategy_group(ranked_strategy.strategy_id)
            grouped_rankings.setdefault(group, []).append(ranked_strategy)

        base_targets = self.get_group_target_weights(market_state)
        present_groups = list(grouped_rankings.keys())
        group_targets: Dict[str, float] = {
            group: float(base_targets.get(group, 0.0))
            for group in present_groups
        }

        zero_weight_groups = [group for group, weight in group_targets.items() if weight <= 0]
        if zero_weight_groups:
            remaining_weight = max(0.0, 1.0 - sum(weight for group, weight in group_targets.items() if weight > 0))
            fallback_weight = remaining_weight / len(zero_weight_groups) if zero_weight_groups else 0.0
            for group in zero_weight_groups:
                group_targets[group] = fallback_weight

        target_sum = sum(group_targets.values())
        if target_sum <= 0:
            equal_group_weight = 1.0 / len(present_groups)
            group_targets = {group: equal_group_weight for group in present_groups}
        else:
            group_targets = {group: weight / target_sum for group, weight in group_targets.items()}

        strategy_weights: Dict[str, float] = {}
        for group, group_rankings in grouped_rankings.items():
            intra_group_weights = allocator.allocate_weights(group_rankings, method=method)
            target_group_weight = group_targets[group]
            for strategy_id, weight in intra_group_weights.items():
                strategy_weights[strategy_id] = round(weight * target_group_weight, 6)

        normalized_total = sum(strategy_weights.values())
        if normalized_total <= 0:
            return {}, group_targets

        normalized_weights = {
            strategy_id: weight / normalized_total
            for strategy_id, weight in strategy_weights.items()
        }
        return normalized_weights, group_targets
