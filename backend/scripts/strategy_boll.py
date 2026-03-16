"""
布林带策略（Bollinger Bands Strategy）
============================================================
策略原理：
    布林带（Bollinger Bands）由 John Bollinger 在1980年代发明，
    由三条线组成：
        上轨（Upper Band）= MA(n) + k × STD(n)
        中轨（Middle Band）= MA(n)         ← 即 SMA
        下轨（Lower Band）= MA(n) - k × STD(n)

    参数通常取 n=20（周期），k=2（标准差倍数）。
    统计上，约 95% 的价格分布在上下轨之间（正态分布假设）。

    【%B 指标】
        %B = (Price - Lower) / (Upper - Lower)
        - %B = 0   : 价格恰好在下轨
        - %B = 0.5 : 价格在中轨
        - %B = 1   : 价格恰好在上轨
        - %B < 0   : 价格突破下轨（超卖）
        - %B > 1   : 价格突破上轨（超买）

    【带宽（Bandwidth）】
        BW = (Upper - Lower) / Middle
        带宽收窄 → 价格即将突破（方向未知）
        带宽扩张 → 趋势加速

    交易策略类型：
    1. 均值回归策略（本文实现）：
       价格触碰下轨 → 超卖 → 买入，期待回归中轨
       价格触碰上轨 → 超买 → 卖出，期待回归中轨
       适合：震荡行情

    2. 突破策略（布林带收口后）：
       价格突破上轨 + 带宽扩张 → 趋势突破 → 买入
       适合：趋势行情

    策略局限：
        - 在强趋势中，价格可能沿轨道运行，均值回归失效
        - 建议配合 RSI 或成交量确认信号
"""

import sys
import os
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy_indicators import bollinger_bands
from strategy_backtest import Backtest, load_binance_data


# ──────────────────────────────────────────────────────────
# 信号函数：均值回归布林带策略
# ──────────────────────────────────────────────────────────
def boll_signal(
    df: pd.DataFrame,
    period: int = 20,
    std_dev: float = 2.0,
    buy_pct_b: float = 0.0,
    sell_pct_b: float = 1.0,
) -> pd.Series:
    """
    布林带均值回归信号

    参数：
        df          : OHLCV DataFrame
        period      : 布林带均线周期，通常 20
        std_dev     : 标准差倍数，通常 2.0
        buy_pct_b   : %B 低于此值触发买入（0=下轨，-0.1=轨下10%）
        sell_pct_b  : %B 高于此值触发卖出（1=上轨，1.1=轨上10%）

    返回：
        pd.Series，值域 {1, -1, 0}

    信号逻辑：
        买入：价格从下轨下方回升穿越下轨（%B 上穿 buy_pct_b）
        卖出：价格从上轨上方回落穿越上轨（%B 下穿 sell_pct_b）
    """
    result = bollinger_bands(df, period, std_dev)
    pct_b = result["boll_pct_b"]

    # 价格回升穿越下轨（从超卖区回归）
    cross_up_lower = (pct_b > buy_pct_b) & (pct_b.shift(1) <= buy_pct_b)
    # 价格回落穿越上轨（从超买区回归）
    cross_down_upper = (pct_b < sell_pct_b) & (pct_b.shift(1) >= sell_pct_b)

    signals = pd.Series(0, index=df.index)
    signals[cross_up_lower] = 1
    signals[cross_down_upper] = -1

    return signals


def boll_breakout_signal(
    df: pd.DataFrame,
    period: int = 20,
    std_dev: float = 2.0,
    squeeze_threshold: float = 0.05,
) -> pd.Series:
    """
    布林带收口突破信号（趋势型）

    逻辑：
        1. 等待布林带收窄（带宽 < squeeze_threshold）
        2. 价格突破上轨 → 买入（趋势向上）
        3. 价格跌破下轨 → 卖出/止损

    参数：
        squeeze_threshold : 带宽阈值，低于此值认为收口
    """
    result = bollinger_bands(df, period, std_dev)
    close = result["close"]
    upper = result["boll_upper"]
    lower = result["boll_lower"]
    bw = result["boll_width"]

    # 前一根处于收口状态
    was_squeezed = bw.shift(1) < squeeze_threshold
    # 突破上轨
    breakout_up = (close > upper) & was_squeezed
    # 跌破下轨
    breakout_down = close < lower

    signals = pd.Series(0, index=df.index)
    signals[breakout_up] = 1
    signals[breakout_down] = -1

    return signals


# ──────────────────────────────────────────────────────────
# 直接运行：布林带策略回测
# ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    SYMBOL = "BTC/USDT"
    TIMEFRAME = "4h"
    LIMIT = 500
    PERIOD = 20
    STD_DEV = 2.0
    BUY_PCT_B = 0.0     # %B = 0，即触碰下轨买入
    SELL_PCT_B = 1.0    # %B = 1，即触碰上轨卖出
    INITIAL_CAPITAL = 10000.0
    COMMISSION = 0.001

    print("=" * 60)
    print("布林带策略（Bollinger Bands）- 回测")
    print("=" * 60)
    print(f"""
策略说明：
  交易对   : {SYMBOL}
  K线周期  : {TIMEFRAME}
  均线周期 : {PERIOD}
  标准差倍数: {STD_DEV}
  初始资金 : ${INITIAL_CAPITAL:,.0f} USDT
  手续费   : {COMMISSION*100:.2f}%（单边）

信号规则（均值回归）：
  买入 : 收盘价从下轨（%B=0）下方回升穿越下轨
  卖出 : 收盘价从上轨（%B=1）上方回落穿越上轨

布林带解读：
  上轨 = MA({PERIOD}) + {STD_DEV}×STD
  中轨 = MA({PERIOD})  ← 均值回归目标
  下轨 = MA({PERIOD}) - {STD_DEV}×STD
  %B   : <0 超卖区，>1 超买区
    """)

    print(f"正在从币安获取 {SYMBOL} {TIMEFRAME} 数据...")
    df = load_binance_data(SYMBOL, TIMEFRAME, limit=LIMIT)
    print(f"获取到 {len(df)} 根K线，{df.index[0].date()} → {df.index[-1].date()}")

    # 展示最新布林带数值
    df_boll = bollinger_bands(df, PERIOD, STD_DEV)
    print("\n最新5根K线布林带值：")
    display_cols = ["close", "boll_upper", "boll_mid", "boll_lower", "boll_pct_b", "boll_width"]
    latest = df_boll[display_cols].tail(5)
    pd.set_option("display.float_format", "{:.4f}".format)
    print(latest.to_string())

    current_pct_b = df_boll["boll_pct_b"].iloc[-1]
    print(f"\n当前 %B = {current_pct_b:.3f}")
    if current_pct_b > 0.8:
        print("  → 接近上轨，超买区域，注意卖出机会")
    elif current_pct_b < 0.2:
        print("  → 接近下轨，超卖区域，注意买入机会")
    else:
        print("  → 价格在布林带中间区域，中性")

    # 信号统计
    signals = boll_signal(df, PERIOD, STD_DEV, BUY_PCT_B, SELL_PCT_B)
    buy_count = (signals == 1).sum()
    sell_count = (signals == -1).sum()
    print(f"\n信号统计：买入 {buy_count} 次，卖出 {sell_count} 次")

    # 回测
    def strategy_func(df):
        return boll_signal(df, PERIOD, STD_DEV, BUY_PCT_B, SELL_PCT_B)

    bt = Backtest(
        df, strategy_func,
        initial_capital=INITIAL_CAPITAL,
        commission=COMMISSION,
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
    )
    result = bt.run()
    result.print_summary()
    result.print_trades()

    # 对比买入持有基准
    print("\n" + "=" * 60)
    print("对比：买入持有策略（市场基准）")
    print("=" * 60)

    def buy_hold(df):
        s = pd.Series(0, index=df.index)
        s.iloc[0] = 1
        s.iloc[-1] = -1
        return s

    bt_bh = Backtest(df, buy_hold, initial_capital=INITIAL_CAPITAL,
                     commission=COMMISSION, symbol=SYMBOL, timeframe=TIMEFRAME)
    bh_result = bt_bh.run()
    bh_result.print_summary()

    alpha = result.total_return - bh_result.total_return
    print(f"\n  策略超额收益（Alpha）: {alpha:+.2f}%")

    # 附加：布林带收口突破策略
    print("\n" + "=" * 60)
    print("附加：布林带收口突破策略（趋势型）")
    print("=" * 60)

    def breakout_func(df):
        return boll_breakout_signal(df, PERIOD, STD_DEV, squeeze_threshold=0.05)

    bt2 = Backtest(
        df, breakout_func,
        initial_capital=INITIAL_CAPITAL,
        commission=COMMISSION,
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
    )
    result2 = bt2.run()
    result2.print_summary()
