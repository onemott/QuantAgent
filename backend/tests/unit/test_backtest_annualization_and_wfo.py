import pandas as pd
import pytest

import app.services.walk_forward.optimizer as wfo_module
from app.api.v1.endpoints.strategy import _run_backtest_engine
from app.services.backtester.annualization import annualize_return, infer_annualization_factor
from app.services.backtester.event_driven import EventDrivenBacktester
from app.services.backtester.vectorized import VectorizedBacktester
from app.services.walk_forward.optimizer import WalkForwardOptimizer


def create_cn_intraday_index(days: int = 2) -> pd.DatetimeIndex:
    sessions = []
    trading_days = pd.bdate_range("2024-01-01", periods=days)
    for day in trading_days:
        morning = pd.date_range(f"{day:%Y-%m-%d} 09:30:00", periods=24, freq="5min")
        afternoon = pd.date_range(f"{day:%Y-%m-%d} 13:00:00", periods=24, freq="5min")
        sessions.extend(morning.tolist())
        sessions.extend(afternoon.tolist())
    return pd.DatetimeIndex(sessions)


def create_crypto_intraday_index(days: int = 7) -> pd.DatetimeIndex:
    return pd.date_range("2024-01-01", periods=days * 288, freq="5min")


def create_daily_dataframe(periods: int = 120) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=periods, freq="D")
    close = pd.Series(range(periods), index=index, dtype=float) + 100.0
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


def test_年化因子_股票日内不再按24小时夸大():
    factor = infer_annualization_factor(create_cn_intraday_index())
    assert factor == 48 * 252


def test_年化因子_连续市场保留全年交易日():
    factor = infer_annualization_factor(create_crypto_intraday_index())
    assert factor == round(288 * 365.2425)


def test_年化因子_连续市场样本未跨周末也不降级():
    factor = infer_annualization_factor(create_crypto_intraday_index(days=5))
    assert factor == round(288 * 365.2425)


def test_事件驱动回测使用统一年化口径():
    index = create_cn_intraday_index(days=3)
    close = pd.Series(range(len(index)), index=index, dtype=float) + 100.0
    df = pd.DataFrame(
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1000.0,
        },
        index=index,
    )

    def signal_func(data):
        signals = pd.Series(0, index=data.index)
        signals.iloc[0] = 1
        return signals

    result = EventDrivenBacktester(df, signal_func, initial_capital=10000.0, commission=0.0).run()

    annualization_factor = infer_annualization_factor(df.index)
    expected_annual = annualize_return(
        result["total_return"] / 100,
        len(df.index) - 1,
        annualization_factor,
    )

    assert result["annual_return"] == pytest.approx(expected_annual)


@pytest.mark.asyncio
async def test_事件驱动回测在运行中事件循环内支持异步信号():
    index = pd.date_range("2024-01-01", periods=5, freq="D")
    close = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0], index=index)
    df = pd.DataFrame(
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1000.0,
        },
        index=index,
    )

    async def signal_func(data):
        signals = pd.Series(0, index=data.index)
        signals.iloc[0] = 1
        return signals

    result = EventDrivenBacktester(df, signal_func, initial_capital=10000.0, commission=0.0).run()

    assert result["total_trades"] == 1
    assert result["final_capital"] > 10000.0


@pytest.mark.asyncio
async def test_向量回测在运行中事件循环内支持异步信号():
    df = create_daily_dataframe(periods=5)

    async def signal_func(data):
        signals = pd.Series(0, index=data.index)
        signals.iloc[-1] = 1
        return signals

    result = VectorizedBacktester(df, signal_func, initial_capital=10000.0, commission=0.0).run()

    assert result["total_trades"] == 0
    assert result["final_position"] == 1.0


def test_内置回测引擎使用统一年化口径():
    index = create_cn_intraday_index(days=3)
    close = pd.Series(range(len(index)), index=index, dtype=float) + 100.0
    df = pd.DataFrame(
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1000.0,
        },
        index=index,
    )

    def signal_func(data):
        signals = pd.Series(0, index=data.index)
        signals.iloc[0] = 1
        return signals

    result = _run_backtest_engine(df, signal_func, 10000.0, "TEST", "5m", commission=0.0)

    annualization_factor = infer_annualization_factor(df.index)
    expected_annual = annualize_return(result["total_return"] / 100, len(df.index) - 1, annualization_factor)

    assert result["annual_return"] == pytest.approx(expected_annual, rel=1e-4)


def test_事件驱动回测信号下一根才成交():
    index = pd.date_range("2024-01-01", periods=3, freq="D")
    df = pd.DataFrame(
        {
            "open": [100.0, 200.0, 200.0],
            "high": [100.0, 200.0, 200.0],
            "low": [100.0, 200.0, 200.0],
            "close": [100.0, 200.0, 200.0],
            "volume": [1000.0, 1000.0, 1000.0],
        },
        index=index,
    )

    def signal_func(data):
        signals = pd.Series(0, index=data.index)
        signals.iloc[0] = 1
        return signals

    result = EventDrivenBacktester(df, signal_func, initial_capital=10000.0, commission=0.0).run()

    assert result["total_return"] == pytest.approx(0.0)


def test_内置回测引擎信号下一根才成交():
    index = pd.date_range("2024-01-01", periods=3, freq="D")
    df = pd.DataFrame(
        {
            "open": [100.0, 200.0, 200.0],
            "high": [100.0, 200.0, 200.0],
            "low": [100.0, 200.0, 200.0],
            "close": [100.0, 200.0, 200.0],
            "volume": [1000.0, 1000.0, 1000.0],
        },
        index=index,
    )

    def signal_func(data):
        signals = pd.Series(0, index=data.index)
        signals.iloc[0] = 1
        return signals

    result = _run_backtest_engine(df, signal_func, 10000.0, "TEST", "1d", commission=0.0)

    assert result["total_return"] < 1.0


@pytest.mark.asyncio
async def test_wfo_拒绝非时间索引避免运行时崩溃():
    df = pd.DataFrame(
        {
            "open": [1.0, 2.0, 3.0],
            "high": [1.0, 2.0, 3.0],
            "low": [1.0, 2.0, 3.0],
            "close": [1.0, 2.0, 3.0],
            "volume": [100.0, 100.0, 100.0],
        }
    )
    optimizer = WalkForwardOptimizer(df, strategy_type="ma")

    result = await optimizer.run_wfo()

    assert "error" in result
    assert "DatetimeIndex" in result["error"]


@pytest.mark.asyncio
async def test_wfo_step_days_会透传到窗口步长(monkeypatch):
    df = create_daily_dataframe()
    optimizer = WalkForwardOptimizer(df, strategy_type="ma")
    captured = {}

    def fake_generate_windows(self, index):
        captured["step_size"] = self.step_size
        return []

    monkeypatch.setattr(wfo_module.WindowManager, "generate_windows", fake_generate_windows)

    result = await optimizer.run_wfo(is_days=60, oos_days=30, step_days=15, n_trials=1, use_numba=False, embargo_days=0)

    assert captured["step_size"] == pd.Timedelta(days=15)
    assert "error" in result


@pytest.mark.asyncio
async def test_wfo_无有效窗口时返回错误而不是伪成功():
    df = create_daily_dataframe(periods=10)
    optimizer = WalkForwardOptimizer(df, strategy_type="ma")

    result = await optimizer.run_wfo(is_days=60, oos_days=30, n_trials=1, use_numba=False, embargo_days=0)

    assert "error" in result
    assert "No valid walk-forward windows" in result["error"]


@pytest.mark.asyncio
async def test_wfo_向量回测通过线程池卸载(monkeypatch):
    df = create_daily_dataframe()
    optimizer = WalkForwardOptimizer(df, strategy_type="ma", initial_capital=10000.0)

    monkeypatch.setattr(
        wfo_module.WindowManager,
        "generate_windows",
        lambda self, index: [{"train": (index[0], index[59]), "test": (index[60], index[89])}],
    )
    monkeypatch.setattr(
        wfo_module.OptunaOptimizer,
        "optimize",
        lambda self, n_trials, use_numba: {"best_params": {"fast": 5, "slow": 20}, "best_sharpe": 1.0},
    )
    monkeypatch.setattr(
        wfo_module,
        "build_signal_func",
        lambda strategy_type, params: (lambda data: pd.Series(0.0, index=data.index)),
    )

    def fake_run(self):
        size = len(self.df)
        return {
            "total_return": 0.0,
            "annual_return": 0.0,
            "max_drawdown": 0.0,
            "sharpe_ratio": 0.0,
            "total_trades": 0,
            "final_capital": float(self.initial_capital),
            "final_position": float(self.initial_position),
            "equity_curve": [float(self.initial_capital)] * size,
            "returns": [0.0] * size,
            "trade_markers": [0.0] * size,
        }

    monkeypatch.setattr(wfo_module.VectorizedBacktester, "run", fake_run)

    call_names = []

    async def fake_to_thread(func, *args, **kwargs):
        call_names.append(getattr(func, "__name__", type(func).__name__))
        return func(*args, **kwargs)

    monkeypatch.setattr(wfo_module.asyncio, "to_thread", fake_to_thread)

    result = await optimizer.run_wfo(is_days=60, oos_days=30, step_days=30, n_trials=1, use_numba=False, embargo_days=0)

    assert "error" not in result
    assert len(call_names) == 3
    assert call_names.count("fake_run") == 2


@pytest.mark.asyncio
async def test_wfo_隔离期信号会在下一窗口正确延续(monkeypatch):
    df = create_daily_dataframe(periods=30)
    df.loc[:, ["open", "high", "low", "close"]] = 100.0
    optimizer = WalkForwardOptimizer(df, strategy_type="ma", initial_capital=10000.0)
    index = df.index

    windows = [
        {"train": (index[0], index[19]), "test": (index[20], index[22])},
        {"train": (index[3], index[22]), "test": (index[24], index[26])},
    ]

    monkeypatch.setattr(wfo_module.WindowManager, "generate_windows", lambda self, data_index: windows)
    monkeypatch.setattr(
        wfo_module.OptunaOptimizer,
        "optimize",
        lambda self, n_trials, use_numba: {"best_params": {"fast": 5, "slow": 20}, "best_sharpe": 1.0},
    )
    monkeypatch.setattr(
        wfo_module,
        "build_signal_func",
        lambda strategy_type, params: (
            lambda data: pd.Series(
                [1.0 if ts == index[19] else -1.0 if ts == index[23] else 0.0 for ts in data.index],
                index=data.index,
            )
        ),
    )

    result = await optimizer.run_wfo(is_days=20, oos_days=3, step_days=3, n_trials=1, use_numba=False, embargo_days=1)

    assert "error" not in result
    second_window = result["walk_forward_results"][1]
    assert second_window["oos_trades"] == 1
    assert second_window["oos_return"] < 0


@pytest.mark.asyncio
async def test_wfo_上一窗口最后一根信号能传递到下一窗口(monkeypatch):
    df = create_daily_dataframe(periods=30)
    df.loc[:, ["open", "high", "low", "close"]] = 100.0
    df.loc[df.index[23]:, ["open", "high", "low", "close"]] = 110.0
    optimizer = WalkForwardOptimizer(df, strategy_type="ma", initial_capital=10000.0)
    index = df.index

    windows = [
        {"train": (index[0], index[19]), "test": (index[20], index[22])},
        {"train": (index[3], index[22]), "test": (index[23], index[25])},
    ]

    monkeypatch.setattr(wfo_module.WindowManager, "generate_windows", lambda self, data_index: windows)
    monkeypatch.setattr(
        wfo_module.OptunaOptimizer,
        "optimize",
        lambda self, n_trials, use_numba: {"best_params": {"fast": 5, "slow": 20}, "best_sharpe": 1.0},
    )
    monkeypatch.setattr(
        wfo_module,
        "build_signal_func",
        lambda strategy_type, params: (
            lambda data: pd.Series([1.0 if ts == index[22] else 0.0 for ts in data.index], index=data.index)
        ),
    )

    result = await optimizer.run_wfo(is_days=20, oos_days=3, step_days=3, n_trials=1, use_numba=False, embargo_days=0)

    assert "error" not in result
    first_window = result["walk_forward_results"][0]
    second_window = result["walk_forward_results"][1]
    assert first_window["oos_trades"] == 0
    assert second_window["oos_return"] > 0
