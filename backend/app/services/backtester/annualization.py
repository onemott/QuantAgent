import math
from typing import Optional

import pandas as pd
from pandas.tseries.frequencies import to_offset


WEEKDAY_TRADING_DAYS_PER_YEAR = 252.0
CONTINUOUS_TRADING_DAYS_PER_YEAR = 365.2425
DEFAULT_ANNUALIZATION_FACTOR = 252
DEFAULT_RISK_FREE_RATE = 0.02


def validate_datetime_index(index: pd.Index, name: str = "Backtest data") -> None:
    if not isinstance(index, pd.DatetimeIndex):
        raise ValueError(f"{name} requires a DatetimeIndex.")
    if len(index) == 0:
        raise ValueError(f"{name} index cannot be empty.")
    if not index.is_monotonic_increasing:
        raise ValueError(f"{name} index must be sorted in ascending order.")


def infer_annualization_factor(index: pd.Index) -> int:
    validate_datetime_index(index)

    freq_factor = _infer_factor_from_frequency(index)
    if freq_factor is not None:
        return freq_factor

    trading_days_per_year = _trading_days_per_year(index)
    bars_per_day = _median_bars_per_trading_day(index)
    factor = int(round(max(bars_per_day, 1.0) * trading_days_per_year))
    return max(factor, 1)


def annualize_return(total_return_ratio: float, periods_observed: int, annualization_factor: int) -> float:
    if periods_observed <= 0 or annualization_factor <= 0:
        return 0.0
    if total_return_ratio <= -1.0:
        return -100.0
    return float(((1 + total_return_ratio) ** (annualization_factor / periods_observed) - 1) * 100)


def annualize_sharpe(returns: pd.Series, annualization_factor: int, risk_free_rate: float = DEFAULT_RISK_FREE_RATE) -> float:
    if annualization_factor <= 0 or returns.empty:
        return 0.0

    risk_free_per_period = risk_free_rate / annualization_factor
    excess_returns = returns - risk_free_per_period
    std = excess_returns.std()
    if std <= 0 or math.isnan(std):
        return 0.0

    return float((excess_returns.mean() / std) * math.sqrt(annualization_factor))


def _infer_factor_from_frequency(index: pd.DatetimeIndex) -> Optional[int]:
    inferred_freq = pd.infer_freq(index)
    if not inferred_freq:
        return None

    offset = to_offset(inferred_freq)
    freq_str = offset.freqstr.upper()
    n = max(getattr(offset, "n", 1), 1)

    if freq_str.startswith(("B", "C")):
        return max(int(round(WEEKDAY_TRADING_DAYS_PER_YEAR / n)), 1)
    if freq_str.startswith("D"):
        return max(int(round(CONTINUOUS_TRADING_DAYS_PER_YEAR / n)), 1)
    if freq_str.startswith("W"):
        return max(int(round(52 / n)), 1)
    if freq_str.startswith(("ME", "M")):
        return max(int(round(12 / n)), 1)
    if freq_str.startswith(("QE", "Q")):
        return max(int(round(4 / n)), 1)
    if freq_str.startswith(("YE", "A", "Y")):
        return max(int(round(1 / n)), 1)

    nanos = getattr(offset, "nanos", None)
    if not nanos or nanos <= 0:
        return None

    seconds_per_bar = nanos / 1_000_000_000
    if seconds_per_bar <= 0:
        return None

    trading_days_per_year = _trading_days_per_year(index)
    factor = int(round((trading_days_per_year * 86400) / seconds_per_bar))
    return max(factor, 1)


def _trading_days_per_year(index: pd.DatetimeIndex) -> float:
    has_weekend_bars = bool((index.dayofweek >= 5).any())
    if has_weekend_bars or _looks_like_continuous_intraday_market(index):
        return CONTINUOUS_TRADING_DAYS_PER_YEAR
    return WEEKDAY_TRADING_DAYS_PER_YEAR


def _median_bars_per_trading_day(index: pd.DatetimeIndex) -> float:
    daily_counts = pd.Series(1, index=index).groupby(index.normalize()).sum()
    if daily_counts.empty:
        return 1.0
    return float(daily_counts.median())


def _looks_like_continuous_intraday_market(index: pd.DatetimeIndex) -> bool:
    if len(index) < 2:
        return False

    deltas = index.to_series().diff().dropna()
    if deltas.empty:
        return False

    median_delta = deltas.median()
    if pd.isna(median_delta) or median_delta >= pd.Timedelta(days=1):
        return False

    bars_per_day = _median_bars_per_trading_day(index)
    observed_seconds_per_day = bars_per_day * median_delta.total_seconds()
    return observed_seconds_per_day >= 0.95 * 86400
