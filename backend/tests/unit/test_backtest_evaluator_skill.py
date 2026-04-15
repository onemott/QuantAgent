import math

import pandas as pd
import pytest

from app.skills.backtest_evaluator import BacktestEvaluatorSkill
from app.skills.core.models import SkillDefinition, SkillType


def build_skill() -> BacktestEvaluatorSkill:
    definition = SkillDefinition(
        skill_id="backtest_evaluator_test",
        name="Backtest Evaluator Test",
        description="Unit test skill definition",
        skill_type=SkillType.CUSTOM,
        version="1.0.0",
    )
    return BacktestEvaluatorSkill(definition)


def test_performance_metrics_use_dynamic_annualization_and_real_drawdown():
    skill = build_skill()

    backtest_result = {
        "initial_capital": 100.0,
        "final_capital": 108.0,
        "annualization_factor": 252,
        "data_period_years": 2.0,
        "period_returns": [0.2, -0.25, 0.2],
        "equity_curve": [100.0, 120.0, 90.0, 108.0],
        "trade_returns": [0.12, -0.05, 0.03],
        "warnings": [],
    }

    metrics = skill._calculate_performance_metrics(backtest_result)

    expected_annual_return = (1.08 ** 0.5) - 1
    assert metrics["annual_return"] == pytest.approx(expected_annual_return, rel=1e-4)
    assert metrics["max_drawdown"] == pytest.approx(-0.25, rel=1e-4)
    assert metrics["max_drawdown_duration"] == 2
    assert metrics["total_trades"] == 3
    assert metrics["winning_trades"] == 2
    assert metrics["losing_trades"] == 1
    assert metrics["win_rate"] == pytest.approx(2 / 3, rel=1e-3)
    assert metrics["avg_win"] == pytest.approx(0.075, rel=1e-4)
    assert metrics["avg_loss"] == pytest.approx(-0.05, rel=1e-4)
    assert metrics["profit_factor"] == pytest.approx(3.0, rel=1e-4)


def test_performance_metrics_sortino_uses_downside_deviation():
    skill = build_skill()
    period_returns = pd.Series([0.02, -0.01, 0.015, -0.03, 0.01], dtype=float)
    equity_curve = [100.0]
    for period_return in period_returns:
        equity_curve.append(equity_curve[-1] * (1 + period_return))

    backtest_result = {
        "initial_capital": 100.0,
        "final_capital": equity_curve[-1],
        "annualization_factor": 252,
        "data_period_years": 1.0,
        "period_returns": period_returns.tolist(),
        "equity_curve": equity_curve,
        "trade_returns": [0.03, -0.02, 0.01],
        "warnings": [],
    }

    metrics = skill._calculate_performance_metrics(backtest_result)

    risk_free_per_period = skill.RISK_FREE_RATE / 252
    excess_returns = period_returns - risk_free_per_period
    expected_volatility = float(period_returns.std(ddof=1) * math.sqrt(252))
    expected_sharpe = float((excess_returns.mean() / excess_returns.std(ddof=1)) * math.sqrt(252))
    expected_downside = float(math.sqrt(((excess_returns.clip(upper=0.0) ** 2).mean())) * math.sqrt(252))
    expected_annual_return = equity_curve[-1] / equity_curve[0] - 1
    expected_sortino = (expected_annual_return - skill.RISK_FREE_RATE) / expected_downside

    assert metrics["volatility"] == pytest.approx(expected_volatility, rel=1e-4)
    assert metrics["sharpe_ratio"] == pytest.approx(expected_sharpe, rel=1e-3)
    assert metrics["downside_deviation"] == pytest.approx(expected_downside, rel=1e-4)
    assert metrics["sortino_ratio"] == pytest.approx(expected_sortino, rel=1e-3)


def test_performance_metrics_zero_trade_and_zero_volatility_are_not_masked():
    skill = build_skill()

    backtest_result = {
        "initial_capital": 100.0,
        "final_capital": 100.0,
        "annualization_factor": 252,
        "data_period_years": 1.0,
        "period_returns": [0.0, 0.0, 0.0],
        "equity_curve": [100.0, 100.0, 100.0, 100.0],
        "trade_returns": [],
        "warnings": [],
    }

    metrics = skill._calculate_performance_metrics(backtest_result)

    assert metrics["total_trades"] == 0
    assert metrics["win_rate"] == 0.0
    assert metrics["profit_factor"] == 0.0
    assert metrics["volatility"] == 0.0
    assert metrics["sharpe_ratio"] == 0.0
    assert metrics["sortino_ratio"] == 0.0
    assert any("零交易策略" in warning for warning in metrics["warnings"])
    assert any("波动率为 0" in warning for warning in metrics["warnings"])
