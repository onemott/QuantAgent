from datetime import datetime, timedelta, timezone

import pytest

from app.core.virtual_bus import VirtualExecutionRouter, VirtualTradingBus
from app.services.dynamic_selection.evaluator import StrategyEvaluator
from scripts import dynamic_selection_backtest


def _build_equity_points():
    base_time = datetime(2025, 1, 1, tzinfo=timezone.utc)
    return [
        (base_time, 1000.0),
        (base_time + timedelta(days=1), 2000.0),
        (base_time + timedelta(days=2), 1500.0),
    ]


def test_window_performance_metric_uses_requested_slice():
    router = VirtualExecutionRouter(initial_capital=1000.0)
    router.equity_curve = _build_equity_points()

    full_metric = router.get_performance_metric()
    window_start = router.equity_curve[1][0]
    window_end = router.equity_curve[2][0]

    window_metric = router.get_performance_metric_in_window(window_start, window_end)

    assert full_metric.total_return == pytest.approx(0.50, abs=1e-6)
    assert window_metric.total_return == pytest.approx(-0.25, abs=1e-6)


def test_backtest_window_evaluation_prefers_recent_window():
    equity_points = _build_equity_points()
    bus = VirtualTradingBus(initial_capital=1000.0)
    bus.router.equity_curve = equity_points

    evaluator = StrategyEvaluator()
    full_evaluation = evaluator.evaluate(
        strategy_id="ma",
        performance=bus.get_performance_metric(),
        window_start=equity_points[0][0],
        window_end=equity_points[-1][0],
        evaluation_date=equity_points[-1][0],
    )

    recent_evaluation = dynamic_selection_backtest.evaluate_strategy_bus_in_window(
        strategy_id="ma",
        bus=bus,
        evaluator=evaluator,
        window_start=equity_points[1][0],
        window_end=equity_points[-1][0],
        evaluation_date=equity_points[-1][0],
    )

    assert recent_evaluation.total_return == pytest.approx(-0.25, abs=1e-6)
    assert full_evaluation.total_return == pytest.approx(0.50, abs=1e-6)
    assert recent_evaluation.total_score != full_evaluation.total_score
    assert recent_evaluation.total_score < full_evaluation.total_score
