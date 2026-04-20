from datetime import datetime, timezone

from scripts.dynamic_selection_backtest import (
    CycleResult,
    ScenarioMetrics,
    ScenarioReport,
    StrategyScore,
    build_cycle_details_dataframe,
    build_cycle_details_text,
)


def _build_report() -> ScenarioReport:
    cycle = CycleResult(
        cycle_index=1,
        window_start=datetime(2025, 1, 1, tzinfo=timezone.utc),
        window_end=datetime(2025, 1, 31, tzinfo=timezone.utc),
        applied_weights={"ma": 0.5, "rsi": 0.5},
        next_weights={"ma": 0.4, "rsi": 0.6},
        strategy_scores={
            "ma": StrategyScore("ma", 62.0, 20.0, 15.0, 12.0, 8.0, 7.0, 1),
            "rsi": StrategyScore("rsi", 70.0, 22.0, 16.0, 13.0, 9.0, 8.0, 2),
        },
        surviving_strategies=["ma", "rsi"],
        eliminated_strategies=[],
        revived_strategies=[],
        elimination_reasons={},
        revival_reasons={},
        strategy_states={"ma": "alive", "rsi": "alive"},
        market_state="range",
        adx_value=18.5,
        portfolio_return=0.03,
        group_target_weights={"trend": 0.4, "oscillator": 0.6},
        primary_downweight_reasons=["趋势族在震荡市降配"],
        primary_upweight_reasons=["震荡族在震荡市增配"],
    )
    metrics = ScenarioMetrics(10000.0, 10300.0, 0.03, 0.03, 0.05, 1.2, 0.6, 5, 3)
    return ScenarioReport(
        scenario_name="开启动态选择",
        enable_dynamic_selection=True,
        evaluation_period_bars=30,
        metrics=metrics,
        cycle_results=[cycle],
    )


def test_cycle_reporting_text_includes_regime_family_weights_and_reasons():
    content = build_cycle_details_text(_build_report())
    assert "当前市场状态: range" in content
    assert "趋势族目标权重: 40.00%" in content
    assert "震荡族目标权重: 60.00%" in content
    assert "本轮主要降权原因: 趋势族在震荡市降配" in content
    assert "本轮主要加权原因: 震荡族在震荡市增配" in content


def test_cycle_reporting_dataframe_includes_expected_columns():
    dataframe = build_cycle_details_dataframe(_build_report())
    assert "当前市场状态" in dataframe.columns
    assert "趋势族目标权重" in dataframe.columns
    assert "震荡族目标权重" in dataframe.columns
    assert "本轮主要降权原因" in dataframe.columns
    assert "本轮主要加权原因" in dataframe.columns
