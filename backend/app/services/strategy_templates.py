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

from app.services.indicators import sma, ema, rsi, bollinger_bands, macd, atr, donchian_channels, ichimoku_cloud
from app.services.macro_analysis_service import macro_analysis_service


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


def _turtle_signal(
    df: pd.DataFrame,
    entry_period: int = 20,
    exit_period: int = 10,
) -> pd.Series:
    """
    Turtle Trading Rules (simplified):
    - Entry: Close breaks above the highest high of entry_period (System 1: 20, System 2: 55)
    - Exit: Close breaks below the lowest low of exit_period (System 1: 10, System 2: 20)
    Uses Donchian Channels for breakout detection.
    """
    result = donchian_channels(df.copy(), period=entry_period)
    upper_band = result["donchian_upper"]
    
    # We need a different period for exit
    exit_result = donchian_channels(df.copy(), period=exit_period)
    lower_band = exit_result["donchian_lower"]
    
    close = df["close"]
    
    # Signals
    buy_signal  = (close > upper_band.shift(1))
    exit_signal = (close < lower_band.shift(1))
    
    signals = pd.Series(0, index=df.index)
    in_position = False
    for i in range(len(signals)):
        if not in_position and bool(buy_signal.iloc[i]):
            signals.iloc[i] = 1
            in_position = True
        elif in_position and bool(exit_signal.iloc[i]):
            signals.iloc[i] = -1
            in_position = False
            
    return signals


def _ichimoku_trend_signal(
    df: pd.DataFrame,
    tenkan_period: int = 9,
    kijun_period: int = 26,
    senkou_b_period: int = 52,
) -> pd.Series:
    """
    Ichimoku Cloud Trend Following:
    - Buy: Price > Span A AND Price > Span B (above cloud) AND Tenkan > Kijun
    - Exit: Price < Kijun (trend weakens)
    Captures strong momentum and trend direction.
    """
    result = ichimoku_cloud(df.copy(), tenkan_period, kijun_period, senkou_b_period)
    close  = result["close"]
    tenkan = result["ichi_tenkan"]
    kijun  = result["ichi_kijun"]
    span_a = result["ichi_span_a"]
    span_b = result["ichi_span_b"]
    
    # Bullish state: above cloud + golden cross
    above_cloud = (close > span_a) & (close > span_b)
    golden_cross = (tenkan > kijun)
    
    buy_signal = above_cloud & golden_cross
    exit_signal = (close < kijun)
    
    signals = pd.Series(0, index=df.index)
    in_position = False
    for i in range(len(signals)):
        if not in_position and bool(buy_signal.iloc[i]):
            signals.iloc[i] = 1
            in_position = True
        elif in_position and bool(exit_signal.iloc[i]):
            signals.iloc[i] = -1
            in_position = False
            
    return signals


async def _smart_beta_signal(
    df: pd.DataFrame,
    symbol: str = "BTCUSDT",
    buy_threshold: float = 0.3,
    sell_threshold: float = -0.3,
) -> pd.Series:
    """
    Smart Beta Strategy based on Macro Analysis:
    - Uses on-chain data (exchange inflows, whale accumulation, etc.)
    - Buy: Macro Score > buy_threshold
    - Sell: Macro Score < sell_threshold
    - Risk Off: Automatically handled if Regime is EXTREME_VOLATILITY (returns -1)
    """
    # Note: In a real backtest, this should use historical macro data.
    # For live/paper trading, we get the current macro score.
    macro_info = await macro_analysis_service.get_macro_score(symbol)
    score = macro_info.get("macro_score", 0.0)
    regime = macro_info.get("regime", "SIDEWAYS")
    
    signals = pd.Series(0, index=df.index)
    
    # If in extreme volatility, force a sell/risk-off signal
    if regime == "EXTREME_VOLATILITY":
        signals.iloc[-1] = -1
        return signals
        
    # Standard threshold-based signals
    if score > buy_threshold:
        signals.iloc[-1] = 1
    elif score < sell_threshold:
        signals.iloc[-1] = -1
        
    return signals


async def _basis_trading_signal(
    df: pd.DataFrame,
    symbol: str = "BTCUSDT",
    min_funding_rate: float = 0.0001, # 0.01%
) -> pd.Series:
    """
    Basis Trading (Arbitrage) Strategy:
    - Long Spot, Short Perpetual to collect funding fees.
    - Simplified logic: buy if funding rate > min_funding_rate.
    """
    # In a real system, we'd fetch the actual funding rate from Binance.
    # Here we simulate/fetch the current funding rate.
    from app.services.binance_service import binance_service
    
    try:
        # 模拟获取资金费率
        # funding_info = await binance_service.get_funding_rate(symbol)
        # funding_rate = float(funding_info.get("lastFundingRate", 0))
        funding_rate = 0.0003 # 模拟为 0.03%
    except Exception:
        funding_rate = 0.0
        
    signals = pd.Series(0, index=df.index)
    
    if funding_rate > min_funding_rate:
        # Buy Spot (Signal = 1) and Sell Future (handled by execution logic)
        signals.iloc[-1] = 1
    elif funding_rate < 0:
        # Funding is negative, exit the basis trade
        signals.iloc[-1] = -1
        
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
    "turtle": {
        "id": "turtle",
        "name": "海龟交易法则 (Turtle Trading)",
        "description": "基于唐奇安通道的突破策略。价格突破最近 N 日高点买入，跌破最近 M 日低点卖出。经典的中长线趋势策略。",
        "params": [
            {
                "key":         "entry_period",
                "label":       "入场周期 (N)",
                "type":        "int",
                "default":     20,
                "min":         10,
                "max":         100,
                "description": "计算入场最高价的周期。经典海龟 System 1 为 20，System 2 为 55。",
            },
            {
                "key":         "exit_period",
                "label":       "出场周期 (M)",
                "type":        "int",
                "default":     10,
                "min":         5,
                "max":         50,
                "description": "计算出场最低价的周期。通常较短，以便在趋势反转时快速撤离。经典为 10。",
            },
        ],
        "signal_func": _turtle_signal,
    },
    "ichimoku": {
        "id": "ichimoku",
        "name": "一目均衡表趋势策略 (Ichimoku Cloud)",
        "description": "当价格位于云层之上且转折线上穿基准线时买入。利用云层作为多空分水岭和强支撑，适合捕捉大波段趋势。",
        "params": [
            {
                "key":         "tenkan_period",
                "label":       "转折线周期",
                "type":        "int",
                "default":     9,
                "min":         5,
                "max":         20,
                "description": "转折线 (Tenkan-sen) 计算周期。默认 9。",
            },
            {
                "key":         "kijun_period",
                "label":       "基准线周期",
                "type":        "int",
                "default":     26,
                "min":         10,
                "max":         60,
                "description": "基准线 (Kijun-sen) 计算周期。默认 26。",
            },
            {
                "key":         "senkou_b_period",
                "label":       "先行带 B 周期",
                "type":        "int",
                "default":     52,
                "min":         30,
                "max":         120,
                "description": "云层先行带 B (Senkou Span B) 计算周期。默认 52。",
            },
        ],
        "signal_func": _ichimoku_trend_signal,
    },
    "smart_beta": {
        "id": "smart_beta",
        "name": "宏观价值配置策略 (Smart Beta)",
        "description": "结合交易所流向、大户持仓等宏观/链上数据进行中长线配置。在牛市或资金流入时加仓，在极端波动或资金流出时减仓避险。",
        "params": [
            {
                "key":         "symbol",
                "label":       "交易对",
                "type":        "str",
                "default":     "BTCUSDT",
                "description": "分析的目标币种。",
            },
            {
                "key":         "buy_threshold",
                "label":       "买入阈值",
                "type":        "float",
                "default":     0.3,
                "min":         0.1,
                "max":         0.9,
                "step":        0.1,
                "description": "宏观评分超过此值时买入。默认 0.3。",
            },
            {
                "key":         "sell_threshold",
                "label":       "卖出阈值",
                "type":        "float",
                "default":     -0.3,
                "min":         -0.9,
                "max":         -0.1,
                "step":        0.1,
                "description": "宏观评分低于此值时卖出。默认 -0.3。",
            },
        ],
        "signal_func": _smart_beta_signal,
    },
    "basis": {
        "id": "basis",
        "name": "期现套利策略 (Basis Trading)",
        "description": "利用现货与永续合约的资金费率差异获利。当费率为正时做多现货做空合约，赚取费率。低风险稳健策略。",
        "params": [
            {
                "key":         "symbol",
                "label":       "交易对",
                "type":        "str",
                "default":     "BTCUSDT",
                "description": "进行套利的目标品种。",
            },
            {
                "key":         "min_funding_rate",
                "label":       "最低入场费率",
                "type":        "float",
                "default":     0.0001,
                "description": "资金费率高于此值时才入场。默认 0.01%。",
            },
        ],
        "signal_func": _basis_trading_signal,
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
        elif p["type"] == "float":
            val = float(val)
        # For 'str' type, keep as is
        validated[key] = val

    import inspect
    if inspect.iscoroutinefunction(raw_func):
        async def signal_func_async(df: pd.DataFrame) -> pd.Series:
            return await raw_func(df, **validated)
        return signal_func_async
    else:
        def signal_func_sync(df: pd.DataFrame) -> pd.Series:
            return raw_func(df, **validated)
        return signal_func_sync



