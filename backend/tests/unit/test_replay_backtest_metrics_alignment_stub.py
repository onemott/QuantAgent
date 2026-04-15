import pandas as pd
import pytest

from app.services.backtester.vectorized import VectorizedBacktester
from app.services.metrics_calculator import StandardizedMetricsSnapshot
from app.services.replay_metrics_service import ReplayMetricsService


def create_sample_dataframe() -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=6, freq="D")
    close = pd.Series([100.0, 102.0, 101.0, 105.0, 108.0, 110.0], index=index)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1000.0,
        },
        index=index,
    )


def buy_and_hold_signal(data: pd.DataFrame) -> pd.Series:
    signals = pd.Series(0.0, index=data.index)
    signals.iloc[0] = 1.0
    return signals


def test_replay_and_backtest_metrics_alignment_stub():
    """
    E2E stub:
    1. 用同一组价格数据跑向量回测链路。
    2. 将相同权益曲线喂给回放链路的公共指标计算入口。
    3. 断言核心指标在标准化后完全一致。
    """
    df = create_sample_dataframe()
    backtester = VectorizedBacktester(df, buy_and_hold_signal, initial_capital=10000.0, commission=0.0)
    backtest_result = backtester.run()

    standardized_backtest = StandardizedMetricsSnapshot(**backtest_result["canonical_metrics"])
    assert backtest_result["metric_types"]["total_return"] == "percentage"
    assert backtest_result["metric_types"]["max_drawdown"] == "percentage"
    assert standardized_backtest.metric_types["total_return"] == "decimal"
    assert standardized_backtest.metric_types["max_drawdown"] == "absolute_value"

    standardized_from_typed_payload = StandardizedMetricsSnapshot.from_source(
        {
            **backtest_result,
            "initial_capital": 10000.0,
        }
    )
    assert standardized_from_typed_payload.total_return == pytest.approx(standardized_backtest.total_return)
    assert standardized_from_typed_payload.max_drawdown_pct == pytest.approx(standardized_backtest.max_drawdown_pct)

    replay_equity_points = [
        {"timestamp": ts, "equity": equity}
        for ts, equity in zip(df.index, backtest_result["equity_curve"])
    ]
    standardized_replay = ReplayMetricsService.build_common_metrics_from_equity_points(
        equity_points=replay_equity_points,
        initial_capital=10000.0,
        total_trades=backtest_result["total_trades"],
        winning_trades=0,
    )

    assert standardized_replay.total_return == pytest.approx(standardized_backtest.total_return)
    assert standardized_replay.annualized_return == pytest.approx(standardized_backtest.annualized_return)
    assert standardized_replay.max_drawdown_pct == pytest.approx(standardized_backtest.max_drawdown_pct)
    assert standardized_replay.volatility == pytest.approx(standardized_backtest.volatility)
    assert standardized_replay.sharpe_ratio == pytest.approx(standardized_backtest.sharpe_ratio)
    assert standardized_replay.sortino_ratio == pytest.approx(standardized_backtest.sortino_ratio)
    assert standardized_replay.calmar_ratio == pytest.approx(standardized_backtest.calmar_ratio)


def test_standardized_metrics_snapshot_handles_legacy_percentage_payload_without_type_tags():
    snapshot = StandardizedMetricsSnapshot.from_source(
        {
            "annualized_return": 24.0,
            "max_drawdown_pct": 8.0,
            "volatility": 12.0,
            "win_rate": 55.0,
            "total_return": 18.0,
            "total_trades": 10,
            "winning_trades": 6,
        }
    )

    assert snapshot.annualized_return == pytest.approx(0.24)
    assert snapshot.max_drawdown_pct == pytest.approx(0.08)
    assert snapshot.volatility == pytest.approx(0.12)
    assert snapshot.win_rate == pytest.approx(0.55)
    assert snapshot.total_return == pytest.approx(0.18)
