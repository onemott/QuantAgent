"""
技术指标库 - 量化交易常用指标计算
============================================================
包含指标：
  - SMA  : 简单移动平均线（Simple Moving Average）
  - EMA  : 指数移动平均线（Exponential Moving Average）
  - BOLL : 布林带（Bollinger Bands）
  - RSI  : 相对强弱指数（Relative Strength Index）
  - MACD : 指数平滑异同移动平均线
  - ATR  : 平均真实波幅（Average True Range）

所有函数均接收 pandas DataFrame（含 open/high/low/close/volume 列），
返回新增指标列后的 DataFrame 副本，不修改原始数据。
"""

import pandas as pd
import numpy as np


# ──────────────────────────────────────────────────────────
# SMA  简单移动平均线
# ──────────────────────────────────────────────────────────
def sma(df: pd.DataFrame, period: int, column: str = "close") -> pd.DataFrame:
    """
    简单移动平均线（SMA）

    计算公式：
        SMA(n) = (P1 + P2 + ... + Pn) / n

    参数：
        df      : OHLCV DataFrame
        period  : 均线周期，如 5、10、20、60
        column  : 计算列，默认 'close'

    返回：
        df 副本，新增列 f'sma_{period}'

    用途：
        判断价格趋势方向。价格在均线上方为上升趋势，下方为下降趋势。
        短期均线（5、10日）反应快，长期均线（60、120日）反应慢。
    """
    result = df.copy()
    result[f"sma_{period}"] = result[column].rolling(window=period).mean()
    return result


# ──────────────────────────────────────────────────────────
# EMA  指数移动平均线
# ──────────────────────────────────────────────────────────
def ema(df: pd.DataFrame, period: int, column: str = "close") -> pd.DataFrame:
    """
    指数移动平均线（EMA）

    计算公式：
        EMA(t) = Price(t) × k + EMA(t-1) × (1 - k)
        其中 k = 2 / (period + 1)

    与 SMA 的区别：
        EMA 对近期价格赋予更高权重，对价格变化响应更灵敏。
        MACD 等指标的核心就是基于 EMA 计算。

    参数：
        df      : OHLCV DataFrame
        period  : 周期
        column  : 计算列，默认 'close'

    返回：
        df 副本，新增列 f'ema_{period}'
    """
    result = df.copy()
    result[f"ema_{period}"] = result[column].ewm(span=period, adjust=False).mean()
    return result


# ──────────────────────────────────────────────────────────
# BOLL  布林带
# ──────────────────────────────────────────────────────────
def bollinger_bands(
    df: pd.DataFrame, period: int = 20, std_dev: float = 2.0, column: str = "close"
) -> pd.DataFrame:
    """
    布林带（Bollinger Bands）

    计算公式：
        中轨（MB）= SMA(period)
        上轨（UB）= MB + std_dev × STD(period)
        下轨（LB）= MB - std_dev × STD(period)
        %B         = (Price - LB) / (UB - LB)  ← 价格在带内相对位置，0~1

    参数：
        df      : OHLCV DataFrame
        period  : 均线周期，通常取 20
        std_dev : 标准差倍数，通常取 2.0
        column  : 计算列，默认 'close'

    返回：
        df 副本，新增列：
            boll_mid   - 中轨
            boll_upper - 上轨
            boll_lower - 下轨
            boll_pct_b - %B 指标
            boll_width - 带宽（衡量波动率）

    交易含义：
        - 价格触碰/突破下轨 → 可能超卖，关注买入机会
        - 价格触碰/突破上轨 → 可能超买，关注卖出机会
        - 带宽收窄 → 行情即将突破，方向不定
        - 带宽扩张 → 趋势确立，波动加剧
    """
    result = df.copy()
    mid = result[column].rolling(window=period).mean()
    std = result[column].rolling(window=period).std(ddof=0)

    result["boll_mid"] = mid
    result["boll_upper"] = mid + std_dev * std
    result["boll_lower"] = mid - std_dev * std
    result["boll_pct_b"] = (result[column] - result["boll_lower"]) / (
        result["boll_upper"] - result["boll_lower"]
    )
    result["boll_width"] = (result["boll_upper"] - result["boll_lower"]) / mid
    return result


# ──────────────────────────────────────────────────────────
# RSI  相对强弱指数
# ──────────────────────────────────────────────────────────
def rsi(df: pd.DataFrame, period: int = 14, column: str = "close") -> pd.DataFrame:
    """
    相对强弱指数（RSI）

    计算公式：
        delta  = Price(t) - Price(t-1)
        gain   = delta 中的正值，负值置0
        loss   = delta 中的负值的绝对值，正值置0
        avg_gain = EMA(gain, period)
        avg_loss = EMA(loss, period)
        RS     = avg_gain / avg_loss
        RSI    = 100 - (100 / (1 + RS))

    参数：
        df      : OHLCV DataFrame
        period  : 计算周期，通常取 14
        column  : 计算列，默认 'close'

    返回：
        df 副本，新增列 f'rsi_{period}'（值域 0~100）

    交易含义：
        - RSI > 70 : 超买区域，价格可能回落
        - RSI < 30 : 超卖区域，价格可能反弹
        - RSI = 50 : 多空平衡线，RSI 上穿50为看多信号
        - RSI 背离 : 价格创新高但 RSI 未创新高，预示趋势减弱
    """
    result = df.copy()
    delta = result[column].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    result[f"rsi_{period}"] = 100 - (100 / (1 + rs))
    return result


# ──────────────────────────────────────────────────────────
# MACD  指数平滑异同移动平均线
# ──────────────────────────────────────────────────────────
def macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    column: str = "close",
) -> pd.DataFrame:
    """
    MACD 指数平滑异同移动平均线

    计算公式：
        DIF（MACD线）= EMA(fast) - EMA(slow)
        DEA（信号线）= EMA(DIF, signal)
        HIST（柱状图）= (DIF - DEA) × 2

    参数：
        df      : OHLCV DataFrame
        fast    : 快线周期，通常取 12
        slow    : 慢线周期，通常取 26
        signal  : 信号线周期，通常取 9
        column  : 计算列，默认 'close'

    返回：
        df 副本，新增列：
            macd_dif  - MACD线（快慢EMA之差）
            macd_dea  - 信号线（DIF的EMA）
            macd_hist - 柱状图（红绿柱）

    交易含义：
        - DIF 上穿 DEA（金叉）→ 买入信号
        - DIF 下穿 DEA（死叉）→ 卖出信号
        - HIST 柱由负转正 → 动能由空转多
        - MACD 背离 : 价格创新高但 MACD 未创新高，趋势减弱警示
    """
    result = df.copy()
    ema_fast = result[column].ewm(span=fast, adjust=False).mean()
    ema_slow = result[column].ewm(span=slow, adjust=False).mean()

    result["macd_dif"] = ema_fast - ema_slow
    result["macd_dea"] = result["macd_dif"].ewm(span=signal, adjust=False).mean()
    result["macd_hist"] = (result["macd_dif"] - result["macd_dea"]) * 2
    return result


# ──────────────────────────────────────────────────────────
# ATR  平均真实波幅
# ──────────────────────────────────────────────────────────
def atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """
    平均真实波幅（ATR, Average True Range）

    计算公式：
        TR（真实波幅）= max(
            High - Low,
            |High - Close(prev)|,
            |Low  - Close(prev)|
        )
        ATR = EMA(TR, period)

    参数：
        df      : OHLCV DataFrame，需含 high/low/close 列
        period  : 计算周期，通常取 14

    返回：
        df 副本，新增列 f'atr_{period}'

    用途（ATR 本身不产生方向信号，用于辅助）：
        - 动态止损：止损价 = 入场价 - N × ATR
        - 仓位管理：用波动率控制单笔风险
        - 突破确认：放量ATR扩大时突破更可靠
    """
    result = df.copy()
    high = result["high"]
    low = result["low"]
    prev_close = result["close"].shift(1)

    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    result[f"atr_{period}"] = tr.ewm(com=period - 1, adjust=False).mean()
    return result


# ──────────────────────────────────────────────────────────
# 批量计算所有指标（演示用）
# ──────────────────────────────────────────────────────────
def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    一次性添加所有常用指标（使用默认参数）

    返回添加了所有指标列的 DataFrame
    """
    result = df.copy()
    result = sma(result, 5)
    result = sma(result, 10)
    result = sma(result, 20)
    result = sma(result, 60)
    result = ema(result, 12)
    result = ema(result, 26)
    result = bollinger_bands(result, 20, 2.0)
    result = rsi(result, 14)
    result = macd(result, 12, 26, 9)
    result = atr(result, 14)
    return result


# ──────────────────────────────────────────────────────────
# 直接运行：展示各指标计算结果
# ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    import os

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app.services.binance_service import BinanceService

    print("=" * 60)
    print("技术指标库演示 - BTC/USDT 1日K线（最近100根）")
    print("=" * 60)

    import asyncio
    
    async def main():
        service = BinanceService()
        try:
            df = await service.get_klines_dataframe("BTC/USDT", "1h", limit=100)
            
            df = add_all_indicators(df)
            
            # 显示最新5根K线的指标值
            cols = [
                "close",
                "sma_5", "sma_20",
                "boll_upper", "boll_mid", "boll_lower", "boll_pct_b",
                "rsi_14",
                "macd_dif", "macd_dea", "macd_hist",
                "atr_14",
            ]
            print("\n最新5根K线的技术指标：")
            pd.set_option("display.float_format", "{:.2f}".format)
            pd.set_option("display.max_columns", None)
            pd.set_option("display.width", 200)
            print(df[cols].tail(5).to_string())
        finally:
            await service.close()

    asyncio.run(main())

    print("\n\n各指标含义速查：")
    print("  SMA(5/20)      : 短期/中期简单均线，判断趋势方向")
    print("  BOLL upper/mid/lower : 布林带上/中/下轨")
    print("  BOLL %B        : 0=下轨, 0.5=中轨, 1=上轨，>1超买，<0超卖")
    print("  RSI(14)        : <30超卖, >70超买, 50为多空分界")
    print("  MACD DIF/DEA   : 金叉(DIF上穿DEA)买入, 死叉卖出")
    print("  ATR(14)        : 近期平均波动幅度，用于止损和仓位管理")
