"""
策略模板注册中心
定义可复用的交易策略模板，支持参数化配置。
每个模板提供：
  - 元数据（名称、描述、参数定义）
  - signal_func(df, **params) -> pd.Series（信号生成函数）

支持的策略：
  - ma          : 均线金叉/死叉
  - rsi         : RSI 超买/超卖
  - boll        : 布林带均值回归
  - macd        : MACD 信号线交叉
  - ema_triple  : 三线 EMA 系统（快/中/慢）
  - atr_trend   : ATR 趋势追踪（动态止损）
  - turtle      : 海龟交易法则（唐奇安通道突破）
  - ichimoku    : 一目均衡表趋势策略
  - smart_beta  : 宏观价值配置策略（异步，不支持历史回放）
  - basis       : 期现套利策略（异步，不支持历史回放）
"""

import logging
import pandas as pd
import numpy as np
from typing import Any, Dict, List, Callable, Optional
from datetime import datetime, timezone

from app.services.indicators import sma, ema, rsi, bollinger_bands, macd, atr, donchian_channels, ichimoku_cloud
from app.services.macro_analysis_service import macro_analysis_service

logger = logging.getLogger(__name__)

# 内存缓存：存储从数据库加载的自定义默认参数（首次访问时刷新）
_db_default_params_cache: Dict[str, Dict[str, float]] = {}
_cache_initialized = False


# ─────────────────────────────────────────────────────────────────────────────
# 信号生成函数
# ─────────────────────────────────────────────────────────────────────────────

def _ma_cross_signal(df: pd.DataFrame, fast_period: int = 10, slow_period: int = 30) -> pd.Series:
    """均线金叉/死叉：金叉买入，死叉卖出。"""
    result = df.copy()
    result = sma(result, fast_period)
    result = sma(result, slow_period)
    fast_col = f"sma_{fast_period}"
    slow_col = f"sma_{slow_period}"
    fast_ma = result[fast_col]
    slow_ma = result[slow_col]

    # 金叉：快线上穿慢线
    cross_up   = (fast_ma > slow_ma) & (fast_ma.shift(1) <= slow_ma.shift(1))
    # 死叉：快线下穿慢线
    cross_down = (fast_ma < slow_ma) & (fast_ma.shift(1) >= slow_ma.shift(1))

    signals = pd.Series(0, index=df.index)
    signals[cross_up]   = 1   # 买入信号
    signals[cross_down] = -1  # 卖出信号
    return signals


def _rsi_signal(
    df: pd.DataFrame,
    rsi_period: int = 14,
    oversold: float = 30.0,
    overbought: float = 70.0,
) -> pd.Series:
    """RSI 超买/超卖：低于超卖线买入，高于超买线卖出。"""
    result = rsi(df.copy(), rsi_period)
    col = f"rsi_{rsi_period}"
    rsi_vals = result[col]

    # 买入信号：RSI 向上穿过超卖阈值
    buy  = (rsi_vals < oversold) & (rsi_vals.shift(1) >= oversold)
    # 卖出信号：RSI 向下穿过超买阈值
    sell = (rsi_vals > overbought) & (rsi_vals.shift(1) <= overbought)

    signals = pd.Series(0, index=df.index)
    signals[buy]  = 1   # 买入信号
    signals[sell] = -1  # 卖出信号
    return signals


def _boll_signal(
    df: pd.DataFrame,
    period: int = 20,
    std_dev: float = 2.0,
    buy_pct_b: float = 0.0,
    sell_pct_b: float = 1.0,
) -> pd.Series:
    """布林带均值回归：触碰下轨买入，触碰上轨卖出。"""
    result = bollinger_bands(df.copy(), period=period, std_dev=std_dev)
    pct_b = result["boll_pct_b"]

    # 价格跌破下轨（%B <= 0）时买入
    buy  = (pct_b <= buy_pct_b)  & (pct_b.shift(1) > buy_pct_b)
    # 价格突破上轨（%B >= 1）时卖出
    sell = (pct_b >= sell_pct_b) & (pct_b.shift(1) < sell_pct_b)

    signals = pd.Series(0, index=df.index)
    signals[buy]  = 1   # 买入信号
    signals[sell] = -1  # 卖出信号
    return signals


def _macd_signal(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> pd.Series:
    """
    MACD 信号线交叉策略：
    - 买入：DIF 线上穿 DEA 信号线（金叉）
    - 卖出：DIF 线下穿 DEA 信号线（死叉）
    结合 MACD 柱状图确认动量方向。
    """
    result = macd(df.copy(), fast=fast, slow=slow, signal=signal_period)
    dif = result["macd_dif"]
    dea = result["macd_dea"]

    # 金叉：DIF 上穿 DEA
    cross_up   = (dif > dea) & (dif.shift(1) <= dea.shift(1))
    # 死叉：DIF 下穿 DEA
    cross_down = (dif < dea) & (dif.shift(1) >= dea.shift(1))

    signals = pd.Series(0, index=df.index)
    signals[cross_up]   = 1   # 买入信号
    signals[cross_down] = -1  # 卖出信号
    return signals


def _ema_triple_signal(
    df: pd.DataFrame,
    fast_period: int = 5,
    mid_period: int = 20,
    slow_period: int = 60,
) -> pd.Series:
    """
    三线 EMA 趋势系统：
    - 买入：快线 > 中线 > 慢线（三线多头排列）
    - 卖出：快线跌破中线（趋势破坏）
    通过三条 EMA 过滤噪音，追踪强趋势行情。
    """
    result = df.copy()
    result = ema(result, fast_period)
    result = ema(result, mid_period)
    result = ema(result, slow_period)

    fast_e = result[f"ema_{fast_period}"]
    mid_e  = result[f"ema_{mid_period}"]
    slow_e = result[f"ema_{slow_period}"]

    # 多头排列：快线 > 中线 > 慢线
    bull_aligned  = (fast_e > mid_e) & (mid_e > slow_e)
    bull_prev     = (fast_e.shift(1) > mid_e.shift(1)) & (mid_e.shift(1) > slow_e.shift(1))
    buy           = bull_aligned & ~bull_prev  # 刚进入多头排列状态

    # 退出信号：快线下穿中线
    bear_entry    = (fast_e < mid_e) & (fast_e.shift(1) >= mid_e.shift(1))

    signals = pd.Series(0, index=df.index)
    signals[buy]        = 1   # 买入信号
    signals[bear_entry] = -1  # 卖出信号
    return signals


def _atr_trend_signal(
    df: pd.DataFrame,
    atr_period: int = 14,
    atr_multiplier: float = 2.0,
    trend_period: int = 20,
) -> pd.Series:
    """
    ATR 趋势追踪策略（吊灯出场法）：
    - 入场：价格突破 trend_period 周期最高价
    - 出场：价格跌破（近期最高价 - atr_multiplier × ATR）的动态止损线
    适合强趋势、高波动市场，可有效规避横盘震荡。
    """
    result = atr(df.copy(), period=atr_period)
    atr_vals   = result[f"atr_{atr_period}"]
    close      = result["close"]
    high       = result["high"]

    # 趋势入场：价格突破滚动最高价
    highest    = high.rolling(window=trend_period).max()
    breakout   = (close > highest.shift(1))

    # 吊灯出场：价格跌破（滚动最高价 - 倍数 × ATR）
    rolling_high    = high.rolling(window=atr_period).max()
    chandelier_stop = rolling_high - atr_multiplier * atr_vals
    exit_signal     = close < chandelier_stop

    signals = pd.Series(0, index=df.index)
    in_position = False
    for i in range(len(signals)):
        if not in_position and bool(breakout.iloc[i]):
            signals.iloc[i] = 1   # 突破入场
            in_position = True
        elif in_position and bool(exit_signal.iloc[i]):
            signals.iloc[i] = -1  # 吊灯止损出场
            in_position = False

    return signals


def _turtle_signal(
    df: pd.DataFrame,
    entry_period: int = 20,
    exit_period: int = 10,
) -> pd.Series:
    """
    海龟交易法则（简化版）：
    - 入场：收盘价突破 entry_period 周期最高价（System 1: 20，System 2: 55）
    - 出场：收盘价跌破 exit_period 周期最低价（System 1: 10，System 2: 20）
    使用唐奇安通道进行突破检测。
    """
    # 计算入场通道（上轨）
    result = donchian_channels(df.copy(), period=entry_period)
    upper_band = result["donchian_upper"]
    
    # 计算出场通道（下轨，使用不同周期）
    exit_result = donchian_channels(df.copy(), period=exit_period)
    lower_band = exit_result["donchian_lower"]
    
    close = df["close"]
    
    # 入场信号：突破上轨
    buy_signal  = (close > upper_band.shift(1))
    # 出场信号：跌破下轨
    exit_signal = (close < lower_band.shift(1))
    
    signals = pd.Series(0, index=df.index)
    in_position = False
    for i in range(len(signals)):
        if not in_position and bool(buy_signal.iloc[i]):
            signals.iloc[i] = 1   # 突破入场
            in_position = True
        elif in_position and bool(exit_signal.iloc[i]):
            signals.iloc[i] = -1  # 跌破出场
            in_position = False
            
    return signals


def _ichimoku_trend_signal(
    df: pd.DataFrame,
    tenkan_period: int = 9,
    kijun_period: int = 26,
    senkou_b_period: int = 52,
) -> pd.Series:
    """
    一目均衡表趋势策略：
    - 买入：价格 > 先行带 A 且价格 > 先行带 B（位于云层之上）且转折线 > 基准线（金叉）
    - 出场：价格跌破基准线（趋势减弱）
    综合判断趋势强度和动量方向。
    """
    result = ichimoku_cloud(df.copy(), tenkan_period, kijun_period, senkou_b_period)
    close  = result["close"]
    tenkan = result["ichi_tenkan"]  # 转折线
    kijun  = result["ichi_kijun"]   # 基准线
    span_a = result["ichi_span_a"]  # 先行带 A
    span_b = result["ichi_span_b"]  # 先行带 B
    
    # 多头状态：位于云层之上 + 金叉
    above_cloud  = (close > span_a) & (close > span_b)
    golden_cross = (tenkan > kijun)
    
    buy_signal  = above_cloud & golden_cross
    exit_signal = (close < kijun)  # 跌破基准线视为趋势减弱
    
    signals = pd.Series(0, index=df.index)
    in_position = False
    for i in range(len(signals)):
        if not in_position and bool(buy_signal.iloc[i]):
            signals.iloc[i] = 1   # 云层上方金叉买入
            in_position = True
        elif in_position and bool(exit_signal.iloc[i]):
            signals.iloc[i] = -1  # 跌破基准线出场
            in_position = False
            
    return signals


async def _smart_beta_signal(
    df: pd.DataFrame,
    symbol: str = "BTCUSDT",
    buy_threshold: float = 0.3,
    sell_threshold: float = -0.3,
) -> pd.Series:
    """
    宏观价值配置策略（Smart Beta）：
    - 利用链上数据（交易所流向、大户积累等）生成信号
    - 买入：宏观评分 > buy_threshold
    - 卖出：宏观评分 < sell_threshold
    - 极端波动时自动触发风险规避（返回 -1）
    注意：此策略为异步策略，不支持历史回放。
    """
    # 注意：真实回测中应使用历史宏观数据。
    # 实盘/模拟盘中使用当前宏观评分。
    macro_info = await macro_analysis_service.get_macro_score(symbol)
    score  = macro_info.get("macro_score", 0.0)
    regime = macro_info.get("regime", "SIDEWAYS")
    
    signals = pd.Series(0, index=df.index)
    
    # 极端波动市场：强制卖出/风险规避
    if regime == "EXTREME_VOLATILITY":
        signals.iloc[-1] = -1
        return signals
        
    # 基于阈值的标准信号逻辑
    if score > buy_threshold:
        signals.iloc[-1] = 1   # 宏观评分高，买入
    elif score < sell_threshold:
        signals.iloc[-1] = -1  # 宏观评分低，卖出
        
    return signals


async def _basis_trading_signal(
    df: pd.DataFrame,
    symbol: str = "BTCUSDT",
    min_funding_rate: float = 0.0001,  # 最低资金费率 0.01%
) -> pd.Series:
    """
    期现套利策略（Basis Trading）：
    - 做多现货 + 做空永续合约，赚取资金费率收益
    - 简化逻辑：资金费率 > min_funding_rate 时买入现货
    注意：此策略为异步策略，不支持历史回放。
    """
    # 实际系统中应从 Binance 获取真实资金费率
    # 此处模拟获取当前资金费率
    from app.services.binance_service import binance_service
    
    try:
        # 模拟获取资金费率（实际可调用 API）
        # funding_info = await binance_service.get_funding_rate(symbol)
        # funding_rate = float(funding_info.get("lastFundingRate", 0))
        funding_rate = 0.0003  # 模拟为 0.03%
    except Exception:
        funding_rate = 0.0
        
    signals = pd.Series(0, index=df.index)
    
    if funding_rate > min_funding_rate:
        # 资金费率为正且超过阈值：买入现货（做空合约由执行层处理）
        signals.iloc[-1] = 1
    elif funding_rate < 0:
        # 资金费率为负：退出套利仓位
        signals.iloc[-1] = -1
        
    return signals


# ─────────────────────────────────────────────────────────────────────────────
# 策略模板注册表
# ─────────────────────────────────────────────────────────────────────────────

# 异步策略集合（依赖实时数据，不支持历史回放）
ASYNC_STRATEGIES = {"smart_beta", "basis"}

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
    """根据策略类型返回模板定义（不含可调用的 signal_func）。"""
    t = STRATEGY_TEMPLATES.get(strategy_type)
    if t is None:
        raise ValueError(f"未知策略类型: {strategy_type}。可用策略: {list(STRATEGY_TEMPLATES.keys())}")
    return t


def update_template_default_params(
    strategy_type: str, 
    new_params: Dict[str, Any],
    updated_by: str = "optimization"
) -> Dict[str, Any]:
    """
    更新策略模板的参数默认值。
    允许将优化后的参数保存为新的默认值。
    
    同时保存到：
    1. 内存缓存（快速访问）
    2. 数据库（跨重启持久化）
    
    Args:
        strategy_type: 策略标识符（如 "ma", "rsi"）
        new_params: 参数键到新默认值的映射字典
        updated_by: 更新来源（"optimization", "manual_backtest", "manual_replay"）
        
    Returns:
        更新后的模板定义
        
    Raises:
        ValueError: 策略类型未知或参数键无效时抛出
    """
    global _db_default_params_cache
    
    if strategy_type not in STRATEGY_TEMPLATES:
        raise ValueError(f"未知策略类型: {strategy_type}。可用策略: {list(STRATEGY_TEMPLATES.keys())}")
    
    template = STRATEGY_TEMPLATES[strategy_type]
    valid_keys = {p["key"] for p in template["params"]}
    
    # 校验参数键合法性
    for key, value in new_params.items():
        if key not in valid_keys:
            raise ValueError(f"策略 '{strategy_type}' 中不存在参数 '{key}'。有效参数: {valid_keys}")
    
    # 更新内存缓存
    if strategy_type not in _db_default_params_cache:
        _db_default_params_cache[strategy_type] = {}
    
    # 收集需要批量保存的参数
    params_to_save = {}
    
    # 更新默认值并收集待保存参数
    for param in template["params"]:
        key = param["key"]
        if key in new_params:
            # 按参数类型进行类型转换
            if param["type"] == "int":
                param["default"] = int(new_params[key])
            elif param["type"] == "float":
                param["default"] = float(new_params[key])
            else:
                param["default"] = new_params[key]
            
            # 更新内存缓存
            _db_default_params_cache[strategy_type][key] = param["default"]
            params_to_save[key] = param["default"]
    
    # 在单一事务中批量保存所有参数到数据库
    if params_to_save:
        _save_all_params_to_db(strategy_type, params_to_save, updated_by)
    
    return template


def _load_db_default_params() -> Dict[str, Dict[str, float]]:
    """从数据库加载自定义默认参数。"""
    global _db_default_params_cache, _cache_initialized
    
    # 已初始化则直接返回缓存
    if _cache_initialized:
        return _db_default_params_cache
    
    try:
        from app.services.database import get_db
        from app.models.db_models import StrategyDefaultParam
        from sqlalchemy import select
        
        _db_default_params_cache = {}
        
        async def _fetch():
            async with get_db() as session:
                stmt = select(StrategyDefaultParam)
                result = await session.execute(stmt)
                rows = result.scalars().all()
                
                for row in rows:
                    if row.strategy_type not in _db_default_params_cache:
                        _db_default_params_cache[row.strategy_type] = {}
                    _db_default_params_cache[row.strategy_type][row.param_key] = float(row.param_value)
                
                _cache_initialized = True
                logger.info(f"从数据库加载了 {len(rows)} 条自定义默认参数: {_db_default_params_cache}")
        
        # 在同步模块中运行异步函数
        from app.core.async_utils import get_safe_event_loop
        import concurrent.futures
        try:
            loop = get_safe_event_loop()
            if loop.is_running():
                # 已在异步上下文中，通过线程池创建新事件循环
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, _fetch())
                    future.result()
            else:
                loop.run_until_complete(_fetch())
        except Exception as e:
            logger.warning(f"无法加载数据库默认参数（数据库可能尚未就绪）: {e}")
            _cache_initialized = True  # 标记已初始化，避免重试
    
    except ImportError as e:
        logger.warning(f"无法导入数据库模块: {e}")
        _cache_initialized = True
    
    return _db_default_params_cache


def _save_param_to_db(strategy_type: str, param_key: str, param_value: float, updated_by: str = "system") -> None:
    """保存单个参数到数据库。"""
    try:
        from app.services.database import get_db
        from app.models.db_models import StrategyDefaultParam, StrategyParamHistory
        from sqlalchemy import select
        
        async def _save():
            async with get_db() as session:
                # 查询是否已存在记录
                stmt = select(StrategyDefaultParam).where(
                    StrategyDefaultParam.strategy_type == strategy_type,
                    StrategyDefaultParam.param_key == param_key
                )
                result = await session.execute(stmt)
                existing = result.scalar_one_or_none()
                
                old_value = float(existing.param_value) if existing else None
                
                if existing:
                    # 更新已有记录
                    existing.param_value = param_value
                    existing.updated_by = updated_by
                    existing.updated_at = datetime.now(timezone.utc)
                else:
                    # 插入新记录
                    session.add(StrategyDefaultParam(
                        strategy_type=strategy_type,
                        param_key=param_key,
                        param_value=param_value,
                        updated_by=updated_by
                    ))
                
                # 记录变更历史
                session.add(StrategyParamHistory(
                    strategy_type=strategy_type,
                    param_key=param_key,
                    old_value=old_value,
                    new_value=param_value,
                    changed_by=updated_by,
                    reason=f"通过 {updated_by} 更新"
                ))
                
                await session.commit()
                logger.info(f"已保存参数 {strategy_type}.{param_key}={param_value}，更新者: {updated_by}")
        
        from app.core.async_utils import get_safe_event_loop
        import concurrent.futures
        try:
            loop = get_safe_event_loop()
            if loop.is_running():
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, _save())
                    future.result(timeout=5)  # 设置超时确保完成
            else:
                loop.run_until_complete(_save())
        except Exception as e:
            logger.warning(f"无法保存参数到数据库: {e}")

    except ImportError as e:
        logger.warning(f"无法导入数据库模块进行保存: {e}")


def _save_all_params_to_db(strategy_type: str, params: Dict[str, float], updated_by: str = "system") -> None:
    """在单一事务中批量保存多个参数到数据库。"""
    try:
        from app.services.database import get_db
        from app.models.db_models import StrategyDefaultParam, StrategyParamHistory
        from sqlalchemy import select
        
        async def _save_all():
            async with get_db() as session:
                for param_key, param_value in params.items():
                    # 查询是否已存在记录
                    stmt = select(StrategyDefaultParam).where(
                        StrategyDefaultParam.strategy_type == strategy_type,
                        StrategyDefaultParam.param_key == param_key
                    )
                    result = await session.execute(stmt)
                    existing = result.scalar_one_or_none()
                    
                    old_value = float(existing.param_value) if existing else None
                    
                    if existing:
                        # 更新已有记录
                        existing.param_value = param_value
                        existing.updated_by = updated_by
                        existing.updated_at = datetime.now(timezone.utc)
                    else:
                        # 插入新记录
                        session.add(StrategyDefaultParam(
                            strategy_type=strategy_type,
                            param_key=param_key,
                            param_value=param_value,
                            updated_by=updated_by
                        ))
                    
                    # 记录变更历史
                    session.add(StrategyParamHistory(
                        strategy_type=strategy_type,
                        param_key=param_key,
                        old_value=old_value,
                        new_value=param_value,
                        changed_by=updated_by,
                        reason=f"通过 {updated_by} 更新"
                    ))
                
                await session.commit()
                logger.info(f"已为策略 {strategy_type} 保存 {len(params)} 个参数，更新者: {updated_by}")
        
        from app.core.async_utils import get_safe_event_loop
        import concurrent.futures
        try:
            loop = get_safe_event_loop()
            if loop.is_running():
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, _save_all())
                    future.result(timeout=10)
            else:
                loop.run_until_complete(_save_all())
        except Exception as e:
            logger.warning(f"无法批量保存参数到数据库: {e}")

    except ImportError as e:
        logger.warning(f"无法导入数据库模块进行批量保存: {e}")


def _get_custom_default_params(strategy_type: str) -> Dict[str, float]:
    """从数据库缓存中获取指定策略的自定义默认参数。"""
    cache = _load_db_default_params()
    return cache.get(strategy_type, {})


def get_all_templates_meta(include_all: bool = False) -> List[Dict[str, Any]]:
    """返回模板元数据列表（可安全 JSON 序列化，不含可调用对象）。
    合并硬编码默认值与数据库存储的自定义默认值。
    
    Args:
        include_all: 为 True 时返回所有策略（含异步策略）；
                     为 False 时仅返回支持历史回放的策略。
    """
    # 加载数据库自定义参数
    db_params = _load_db_default_params()
    
    result = []
    for t in STRATEGY_TEMPLATES.values():
        strategy_id = t["id"]
        supports_replay = strategy_id not in ASYNC_STRATEGIES  # 是否支持历史回放
        
        # 不包含全部时，跳过异步策略
        if not include_all and not supports_replay:
            continue
        
        # 获取数据库中的自定义参数覆盖值
        custom_params = db_params.get(strategy_id, {})
        
        # 合并参数：数据库值覆盖硬编码默认值
        merged_params = []
        for param in t["params"]:
            param_copy = param.copy()
            if param["key"] in custom_params:
                param_copy["default"] = custom_params[param["key"]]
                param_copy["is_custom"] = True  # 标记为已自定义
            merged_params.append(param_copy)
        
        result.append({
            "id":              strategy_id,
            "name":            t["name"],
            "description":     t["description"],
            "params":          merged_params,
            "supports_replay": supports_replay,
        })
    return result


def get_template_default_params(strategy_type: str) -> Dict[str, float]:
    """获取策略的当前默认参数（合并数据库自定义值与硬编码默认值）。"""
    template = get_template(strategy_type)
    custom = _get_custom_default_params(strategy_type)
    
    defaults = {}
    for p in template["params"]:
        key = p["key"]
        # 优先使用数据库自定义值，否则使用硬编码默认值
        defaults[key] = custom.get(key, p["default"])
    return defaults


def get_replay_templates() -> List[Dict[str, Any]]:
    """仅返回支持历史回放的策略（排除异步策略）。"""
    return get_all_templates_meta(include_all=False)


def _safe_signal_wrapper(raw_func, validated: Dict[str, Any], is_async: bool = False):
    """
    对信号函数进行安全包装，捕获常见计算异常。
    异常时返回全 0 Series（无信号），并记录 WARNING 日志。
    """
    if is_async:
        async def signal_func_async(df: pd.DataFrame) -> pd.Series:
            try:
                # 检查 DataFrame 有效性
                if df is None or df.empty:
                    logger.warning("信号函数收到空 DataFrame，返回全 0 信号")
                    return pd.Series(0, index=pd.DatetimeIndex([]))
                result = await raw_func(df, **validated)
                return _sanitize_signal_result(result, df)
            except Exception as e:
                logger.warning(f"异步信号函数异常: {type(e).__name__}: {e}，返回全 0 信号")
                return pd.Series(0, index=df.index if df is not None else pd.DatetimeIndex([]))
        return signal_func_async
    else:
        def signal_func_sync(df: pd.DataFrame) -> pd.Series:
            try:
                # 检查 DataFrame 有效性
                if df is None or df.empty:
                    logger.warning("信号函数收到空 DataFrame，返回全 0 信号")
                    return pd.Series(0, index=pd.DatetimeIndex([]))
                result = raw_func(df, **validated)
                return _sanitize_signal_result(result, df)
            except Exception as e:
                logger.warning(f"信号函数异常: {type(e).__name__}: {e}，返回全 0 信号")
                return pd.Series(0, index=df.index if df is not None else pd.DatetimeIndex([]))
        return signal_func_sync


def _sanitize_signal_result(result: Any, df: pd.DataFrame) -> pd.Series:
    """
    清理信号函数返回结果，处理 NaN/Inf、空 Series、索引不匹配等问题。
    """
    # 检查结果类型
    if result is None:
        logger.warning("信号函数返回 None，返回全 0 信号")
        return pd.Series(0, index=df.index)

    if not isinstance(result, pd.Series):
        logger.warning(f"信号函数返回类型异常: {type(result)}，返回全 0 信号")
        return pd.Series(0, index=df.index)

    # 处理空 Series
    if len(result) == 0:
        logger.warning("信号函数返回空 Series，返回全 0 信号")
        return pd.Series(0, index=df.index)

    # 处理索引不匹配
    if not result.index.equals(df.index):
        # 尝试重新索引
        try:
            result = result.reindex(df.index, fill_value=0)
        except Exception as e:
            logger.warning(f"信号结果索引重排失败: {e}，返回全 0 信号")
            return pd.Series(0, index=df.index)

    # 处理 NaN/Inf 值
    if result.isna().any() or np.isinf(result).any():
        nan_count = result.isna().sum()
        inf_count = np.isinf(result).sum()
        logger.warning(f"信号结果包含 {nan_count} 个 NaN 和 {inf_count} 个 Inf，已替换为 0")
        result = result.replace([np.inf, -np.inf], 0).fillna(0)

    # 确保信号值为整数（-1, 0, 1）
    result = result.astype(int)

    return result


def build_signal_func(strategy_type: str, params: Dict[str, Any]) -> Callable:
    """返回一个已绑定参数的信号函数 signal_func(df) -> pd.Series。"""
    template = get_template(strategy_type)
    raw_func = template["signal_func"]

    # 校验并转换参数类型
    validated = {}
    for p in template["params"]:
        key = p["key"]
        val = params.get(key, p["default"])
        if p["type"] == "int":
            val = int(val)
        elif p["type"] == "float":
            val = float(val)
        # str 类型保持原样
        validated[key] = val

    import inspect
    is_async = inspect.iscoroutinefunction(raw_func)

    # 返回安全包装的信号函数
    return _safe_signal_wrapper(raw_func, validated, is_async)
