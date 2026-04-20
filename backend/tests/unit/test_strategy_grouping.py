from app.services.dynamic_selection.strategy_grouping import (
    OSCILLATOR_STRATEGIES,
    TREND_STRATEGIES,
    StrategyGrouping,
)


def test_trend_family_contains_expected_strategies():
    expected = {"ma", "macd", "ema_triple", "atr_trend", "turtle", "ichimoku"}
    assert expected.issubset(set(TREND_STRATEGIES))


def test_oscillator_family_contains_expected_strategies():
    expected = {"rsi", "boll"}
    assert expected.issubset(set(OSCILLATOR_STRATEGIES))


def test_regime_target_weights_change_by_market_state():
    grouping = StrategyGrouping()

    trend_targets = grouping.get_group_target_weights("trend_up")
    range_targets = grouping.get_group_target_weights("range")
    high_vol_targets = grouping.get_group_target_weights("high_vol")

    assert trend_targets["trend"] == 0.7
    assert trend_targets["oscillator"] == 0.3
    assert range_targets["oscillator"] == 0.6
    assert range_targets["trend"] == 0.4
    assert high_vol_targets["trend"] == 0.5
    assert high_vol_targets["oscillator"] == 0.5
