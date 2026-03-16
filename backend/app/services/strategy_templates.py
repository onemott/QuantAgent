"""
Strategy Templates Registry
Defines reusable trading strategy templates with configurable parameters.
Each template provides:
  - metadata (name, description, param definitions)
  - signal_func(df, **params) -> pd.Series

Supported strategies:
  - ma          : MA Golden/Death Cross
  - rsi         : RSI Overbought/Oversold
  - boll        : Bollinger Bands Mean Reversion
  - macd        : MACD Signal Line Crossover
  - ema_triple  : Triple EMA System (fast/mid/slow)
  - atr_trend   : ATR-based Trend Following with dynamic stop-loss
"""

import pandas as pd
import numpy as np
from typing import Any, Dict, List, Callable

from app.services.indicators import sma, ema, rsi, bollinger_bands, macd, atr


# ─────────────────────────────────────────────────────────────────────────────
# Signal Functions
# ─────────────────────────────────────────────────────────────────────────────

def _ma_cross_signal(df: pd.DataFrame, fast_period: int = 10, slow_period: int = 30) -> pd.Series:
    """MA Golden/Death Cross: buy on golden cross, sell on death cross."""
    result = df.copy()
    result = sma(result, fast_period)
    result = sma(result, slow_period)
    fast_col = f"sma_{fast_period}"
    slow_col = f"sma_{slow_period}"
    fast_ma = result[fast_col]
    slow_ma = result[slow_col]

    cross_up   = (fast_ma > slow_ma) & (fast_ma.shift(1) <= slow_ma.shift(1))
    cross_down = (fast_ma < slow_ma) & (fast_ma.shift(1) >= slow_ma.shift(1))

    signals = pd.Series(0, index=df.index)
    signals[cross_up]   = 1
    signals[cross_down] = -1
    return signals


def _rsi_signal(
    df: pd.DataFrame,
    rsi_period: int = 14,
    oversold: float = 30.0,
    overbought: float = 70.0,
) -> pd.Series:
    """RSI overbought/oversold: buy below oversold, sell above overbought."""
    result = rsi(df.copy(), rsi_period)
    col = f"rsi_{rsi_period}"
    rsi_vals = result[col]

    # Buy signal: RSI crosses UP through oversold threshold
    buy  = (rsi_vals < oversold) & (rsi_vals.shift(1) >= oversold)
    # Sell signal: RSI crosses DOWN through overbought threshold
    sell = (rsi_vals > overbought) & (rsi_vals.shift(1) <= overbought)

    signals = pd.Series(0, index=df.index)
    signals[buy]  = 1
    signals[sell] = -1
    return signals


def _boll_signal(
    df: pd.DataFrame,
    period: int = 20,
    std_dev: float = 2.0,
    buy_pct_b: float = 0.0,
    sell_pct_b: float = 1.0,
) -> pd.Series:
    """Bollinger Bands mean-reversion: buy at lower band, sell at upper band."""
    result = bollinger_bands(df.copy(), period=period, std_dev=std_dev)
    pct_b = result["boll_pct_b"]

    buy  = (pct_b <= buy_pct_b)  & (pct_b.shift(1) > buy_pct_b)
    sell = (pct_b >= sell_pct_b) & (pct_b.shift(1) < sell_pct_b)

    signals = pd.Series(0, index=df.index)
    signals[buy]  = 1
    signals[sell] = -1
    return signals


def _macd_signal(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> pd.Series:
    """
    MACD Signal Line Crossover:
    - Buy when DIF crosses above DEA (golden cross)
    - Sell when DIF crosses below DEA (death cross)
    Also requires MACD histogram to confirm momentum direction.
    """
    result = macd(df.copy(), fast=fast, slow=slow, signal=signal_period)
    dif = result["macd_dif"]
    dea = result["macd_dea"]

    cross_up   = (dif > dea) & (dif.shift(1) <= dea.shift(1))
    cross_down = (dif < dea) & (dif.shift(1) >= dea.shift(1))

    signals = pd.Series(0, index=df.index)
    signals[cross_up]   = 1
    signals[cross_down] = -1
    return signals


def _ema_triple_signal(
    df: pd.DataFrame,
    fast_period: int = 5,
    mid_period: int = 20,
    slow_period: int = 60,
) -> pd.Series:
    """
    Triple EMA Trend System:
    - Buy when fast EMA > mid EMA > slow EMA (all aligned upward)
    - Sell when fast EMA < mid EMA (trend breaks down)
    Uses three EMAs to filter noise and follow strong trends.
    """
    result = df.copy()
    result = ema(result, fast_period)
    result = ema(result, mid_period)
    result = ema(result, slow_period)

    fast_e = result[f"ema_{fast_period}"]
    mid_e  = result[f"ema_{mid_period}"]
    slow_e = result[f"ema_{slow_period}"]

    # Bullish alignment: fast > mid > slow
    bull_aligned  = (fast_e > mid_e) & (mid_e > slow_e)
    bull_prev     = (fast_e.shift(1) > mid_e.shift(1)) & (mid_e.shift(1) > slow_e.shift(1))
    buy           = bull_aligned & ~bull_prev  # transition into bull state

    # Exit: fast crosses below mid
    bear_entry    = (fast_e < mid_e) & (fast_e.shift(1) >= mid_e.shift(1))

    signals = pd.Series(0, index=df.index)
    signals[buy]        = 1
    signals[bear_entry] = -1
    return signals


def _atr_trend_signal(
    df: pd.DataFrame,
    atr_period: int = 14,
    atr_multiplier: float = 2.0,
    trend_period: int = 20,
) -> pd.Series:
    """
    ATR-based Trend Following with Chandelier Exit:
    - Entry: price breaks above the highest high of trend_period candles
    - Exit: price drops more than atr_multiplier × ATR below recent high (chandelier stop)
    Suitable for strong trending markets; avoids choppy sideways action.
    """
    result = atr(df.copy(), period=atr_period)
    atr_vals   = result[f"atr_{atr_period}"]
    close      = result["close"]
    high       = result["high"]

    # Trend entry: close breaks above rolling highest high
    highest    = high.rolling(window=trend_period).max()
    breakout   = (close > highest.shift(1))

    # Chandelier exit: close drops below (rolling high - multiplier × ATR)
    rolling_high   = high.rolling(window=atr_period).max()
    chandelier_stop = rolling_high - atr_multiplier * atr_vals
    exit_signal    = close < chandelier_stop

    signals = pd.Series(0, index=df.index)
    in_position = False
    for i in range(len(signals)):
        if not in_position and bool(breakout.iloc[i]):
            signals.iloc[i] = 1
            in_position = True
        elif in_position and bool(exit_signal.iloc[i]):
            signals.iloc[i] = -1
            in_position = False

    return signals


# ─────────────────────────────────────────────────────────────────────────────
# Template Registry
# ─────────────────────────────────────────────────────────────────────────────

STRATEGY_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "ma": {
        "id": "ma",
        "name": "均线金叉策略 (MA Cross)",
        "description": "短期均线上穿长期均线时买入（金叉），下穿时卖出（死叉）。适合趋势行情。",
        "params": [
            {
                "key":         "fast_period",
                "label":       "快线周期",
                "type":        "int",
                "default":     10,
                "min":         2,
                "max":         50,
                "description": "短期移动平均线周期，用于捕捉近期价格趋势。数值越小越敏感。",
            },
            {
                "key":         "slow_period",
                "label":       "慢线周期",
                "type":        "int",
                "default":     30,
                "min":         5,
                "max":         200,
                "description": "长期移动平均线周期，用于确认主要趋势方向。数值越大越稳定。",
            },
        ],
        "signal_func": _ma_cross_signal,
    },
    "rsi": {
        "id": "rsi",
        "name": "RSI 超买超卖策略",
        "description": "RSI 低于超卖线时买入，高于超买线时卖出。适合震荡行情。",
        "params": [
            {
                "key":         "rsi_period",
                "label":       "RSI 周期",
                "type":        "int",
                "default":     14,
                "min":         2,
                "max":         50,
                "description": "RSI 计算周期，决定指标的敏感度。常用值 14，短线可减小。",
            },
            {
                "key":         "oversold",
                "label":       "超卖线",
                "type":        "float",
                "default":     30.0,
                "min":         10.0,
                "max":         45.0,
                "step":        1.0,
                "description": "RSI 低于此值视为超卖，产生买入信号。默认 30，越低信号越少但越可靠。",
            },
            {
                "key":         "overbought",
                "label":       "超买线",
                "type":        "float",
                "default":     70.0,
                "min":         55.0,
                "max":         90.0,
                "step":        1.0,
                "description": "RSI 高于此值视为超买，产生卖出信号。默认 70，越高信号越少但越可靠。",
            },
        ],
        "signal_func": _rsi_signal,
    },
    "boll": {
        "id": "boll",
        "name": "布林带均值回归策略",
        "description": "价格触碰布林带下轨时买入，触碰上轨时卖出。适合区间震荡行情。",
        "params": [
            {
                "key":         "period",
                "label":       "布林带周期",
                "type":        "int",
                "default":     20,
                "min":         5,
                "max":         100,
                "description": "计算布林带中轨的均线周期。常用 20 日，决定通道的平滑程度。",
            },
            {
                "key":         "std_dev",
                "label":       "标准差倍数",
                "type":        "float",
                "default":     2.0,
                "min":         1.0,
                "max":         4.0,
                "step":        0.5,
                "description": "标准差倍数决定通道宽度。默认 2 倍，越大通道越宽，信号越少。",
            },
        ],
        "signal_func": _boll_signal,
    },
    "macd": {
        "id": "macd",
        "name": "MACD 金叉死叉策略",
        "description": "MACD DIF 线上穿 DEA 信号线（金叉）时买入，下穿（死叉）时卖出。趋势确认型策略。",
        "params": [
            {
                "key":         "fast",
                "label":       "快线周期 (EMA)",
                "type":        "int",
                "default":     12,
                "min":         3,
                "max":         30,
                "description": "快线 EMA 周期。默认 12，与慢线差值形成 DIF 线。",
            },
            {
                "key":         "slow",
                "label":       "慢线周期 (EMA)",
                "type":        "int",
                "default":     26,
                "min":         10,
                "max":         60,
                "description": "慢线 EMA 周期。默认 26，与快线差值形成 DIF 线。",
            },
            {
                "key":         "signal_period",
                "label":       "信号线周期",
                "type":        "int",
                "default":     9,
                "min":         3,
                "max":         20,
                "description": "DEA 信号线周期，对 DIF 线进行平滑处理。默认 9。",
            },
        ],
        "signal_func": _macd_signal,
    },
    "ema_triple": {
        "id": "ema_triple",
        "name": "三线 EMA 趋势系统",
        "description": "快中慢三条 EMA 同向排列时确认趋势买入，快线跌破中线时退出。适合强趋势行情。",
        "params": [
            {
                "key":         "fast_period",
                "label":       "快线周期",
                "type":        "int",
                "default":     5,
                "min":         2,
                "max":         20,
                "description": "快线 EMA 周期，用于捕捉短期趋势变化。默认 5。",
            },
            {
                "key":         "mid_period",
                "label":       "中线周期",
                "type":        "int",
                "default":     20,
                "min":         10,
                "max":         60,
                "description": "中线 EMA 周期，作为趋势确认和退出参考。默认 20。",
            },
            {
                "key":         "slow_period",
                "label":       "慢线周期",
                "type":        "int",
                "default":     60,
                "min":         30,
                "max":         200,
                "description": "慢线 EMA 周期，用于确认长期趋势方向。默认 60。",
            },
        ],
        "signal_func": _ema_triple_signal,
    },
    "atr_trend": {
        "id": "atr_trend",
        "name": "ATR 趋势追踪 (Chandelier Exit)",
        "description": "价格突破高点后入场，使用 ATR 动态止损（吊灯出场法）。适合强趋势、高波动标的。",
        "params": [
            {
                "key":         "atr_period",
                "label":       "ATR 周期",
                "type":        "int",
                "default":     14,
                "min":         5,
                "max":         30,
                "description": "ATR 计算周期，衡量市场波动率。默认 14，短线可减小。",
            },
            {
                "key":         "atr_multiplier",
                "label":       "ATR 倍数（止损）",
                "type":        "float",
                "default":     2.0,
                "min":         1.0,
                "max":         5.0,
                "step":        0.5,
                "description": "止损距离 = ATR × 倍数。默认 2 倍，越大止损越宽松，承受回撤越多。",
            },
            {
                "key":         "trend_period",
                "label":       "趋势突破周期",
                "type":        "int",
                "default":     20,
                "min":         5,
                "max":         60,
                "description": "突破此周期最高价时产生买入信号。默认 20，越大信号越少但趋势越强。",
            },
        ],
        "signal_func": _atr_trend_signal,
    },
}


def get_template(strategy_type: str) -> Dict[str, Any]:
    """Return template definition (without the callable signal_func)."""
    t = STRATEGY_TEMPLATES.get(strategy_type)
    if t is None:
        raise ValueError(f"Unknown strategy type: {strategy_type}. Available: {list(STRATEGY_TEMPLATES.keys())}")
    return t


def get_all_templates_meta() -> List[Dict[str, Any]]:
    """Return template metadata list (safe for JSON serialization, no callables)."""
    result = []
    for t in STRATEGY_TEMPLATES.values():
        result.append({
            "id":          t["id"],
            "name":        t["name"],
            "description": t["description"],
            "params":      t["params"],
        })
    return result


def build_signal_func(strategy_type: str, params: Dict[str, Any]) -> Callable:
    """Return a signal_func(df) -> pd.Series with params baked in."""
    template = get_template(strategy_type)
    raw_func = template["signal_func"]

    # Validate and cast params
    validated = {}
    for p in template["params"]:
        key = p["key"]
        val = params.get(key, p["default"])
        if p["type"] == "int":
            val = int(val)
        else:
            val = float(val)
        validated[key] = val

    def signal_func(df: pd.DataFrame) -> pd.Series:
        return raw_func(df, **validated)

    return signal_func



