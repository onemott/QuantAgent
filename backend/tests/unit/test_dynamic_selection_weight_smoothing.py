import pytest

from scripts.dynamic_selection_backtest import smooth_weight_transition


def test_new_weights_do_not_replace_old_weights_immediately():
    previous_weights = {"ma": 0.7, "rsi": 0.3}
    target_weights = {"ma": 0.1, "rsi": 0.9}

    smoothed = smooth_weight_transition(
        previous_weights,
        target_weights,
        blend_old=0.7,
        blend_new=0.3,
        min_weight_floor=0.05,
        max_single_strategy_weight=0.8,
    )

    assert smoothed["ma"] == pytest.approx(0.52, abs=1e-6)
    assert smoothed["rsi"] == pytest.approx(0.48, abs=1e-6)


def test_single_strategy_weight_respects_cap_after_smoothing():
    smoothed = smooth_weight_transition(
        previous_weights={"ma": 0.2, "rsi": 0.8},
        target_weights={"ma": 0.95, "rsi": 0.05},
        blend_old=0.7,
        blend_new=0.3,
        min_weight_floor=0.05,
        max_single_strategy_weight=0.6,
    )

    assert smoothed["ma"] <= 0.6
    assert smoothed["rsi"] >= 0.05


def test_smoothed_weights_sum_to_one():
    smoothed = smooth_weight_transition(
        previous_weights={"ma": 0.2, "rsi": 0.3, "boll": 0.5},
        target_weights={"ma": 0.6, "rsi": 0.2, "boll": 0.2},
        blend_old=0.7,
        blend_new=0.3,
        min_weight_floor=0.05,
        max_single_strategy_weight=0.7,
    )

    assert sum(smoothed.values()) == pytest.approx(1.0, abs=1e-6)
