from app.models.db_models import StrategyEvaluation
from app.services.dynamic_selection.eliminator import (
    EliminationRule,
    StrategyEliminator,
)
from app.services.dynamic_selection.ranker import RankedStrategy
from app.services.dynamic_selection.weight_allocator import WeightAllocator
from scripts.dynamic_selection_backtest import constrain_weight_step_change


def test_allocator_keeps_minimum_weight_floor():
    allocator = WeightAllocator()
    strategies = [
        RankedStrategy("ma", 90.0, 1, StrategyEvaluation(strategy_id="ma", total_score=90.0)),
        RankedStrategy("rsi", 8.0, 2, StrategyEvaluation(strategy_id="rsi", total_score=8.0)),
        RankedStrategy("boll", 2.0, 3, StrategyEvaluation(strategy_id="boll", total_score=2.0)),
        RankedStrategy("macd", 1.0, 4, StrategyEvaluation(strategy_id="macd", total_score=1.0)),
    ]

    weights = allocator.allocate_weights(
        strategies,
        method="score_based",
        min_weight_floor=0.05,
        max_single_strategy_weight=0.25,
    )

    assert weights["rsi"] >= 0.05
    assert weights["boll"] >= 0.05
    assert weights["macd"] >= 0.05
    assert max(weights.values()) <= 0.25


def test_only_extreme_mismatch_strategies_hibernate():
    eliminator = StrategyEliminator()
    rule = EliminationRule(
        min_score_threshold=25.0,
        elimination_ratio=0.2,
        min_consecutive_low=3,
        low_score_threshold=45.0,
        min_strategies=3,
    )
    ranked = [
        RankedStrategy("ma", 80.0, 1, StrategyEvaluation(strategy_id="ma", total_score=80.0)),
        RankedStrategy("rsi", 50.0, 2, StrategyEvaluation(strategy_id="rsi", total_score=50.0)),
        RankedStrategy("boll", 12.0, 3, StrategyEvaluation(strategy_id="boll", total_score=12.0)),
        RankedStrategy("macd", 10.0, 4, StrategyEvaluation(strategy_id="macd", total_score=10.0)),
    ]
    consecutive_low = {"boll": 3, "macd": 3}
    regime_alignment = {"boll": False, "macd": True}

    surviving, eliminated, _ = eliminator.apply_soft_elimination(
        ranked,
        rule=rule,
        consecutive_low_counts=consecutive_low,
        regime_alignment=regime_alignment,
    )

    assert "boll" in [item.strategy_id for item in eliminated]
    assert "macd" in [item.strategy_id for item in surviving]


def test_weight_change_is_bounded_per_round():
    previous_weights = {"ma": 0.10, "rsi": 0.10, "boll": 0.80}
    target_weights = {"ma": 0.35, "rsi": 0.05, "boll": 0.60}

    constrained = constrain_weight_step_change(
        previous_weights,
        target_weights,
        max_step_change=0.10,
    )

    assert constrained["ma"] <= 0.20
    assert constrained["boll"] >= 0.70
