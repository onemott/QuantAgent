"""
均线交叉策略（MA Cross Strategy）
============================================================
策略原理：
    均线（Moving Average）是将一段时间内的收盘价取平均值，
    平滑掉短期价格波动，揭示价格的中长期趋势。

    【金叉 / 死叉】
    - 金叉（Golden Cross）: 短期均线 上穿 长期均线
      含义：近期价格涨势超过长期均价，上升动能增强 → 买入信号
    - 死叉（Death Cross）: 短期均线 下穿 长期均线
      含义：近期价格跌势强于长期均价，下行压力增大 → 卖出信号

    常用参数组合：
        短线交易：SMA(5) × SMA(10)
        中线交易：SMA(10) × SMA(30) 或 SMA(20) × SMA(60)
        长线交易：SMA(50) × SMA(200)

    策略局限：
        - 属于趋势跟踪策略，在震荡行情中频繁假信号
        - 均线具有滞后性，入场/出场时机略晚
        - 需配合成交量、ATR等过滤噪音
"""

import sys
import os
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy_indicators import sma, ema
from strategy_backtest import Backtest, load_binance_data


# ──────────────────────────────────────────────────────────
# 信号函数
# ──────────────────────────────────────────────────────────
def ma_cross_signal(
    df: pd.DataFrame,
    short_period: int = 10,
    long_period: int = 30,
    ma_type: str = "sma",
) -> pd.Series:
    """
    均线交叉信号生成器

    参数：
        df           : OHLCV DataFrame
        short_period : 短期均线周期，如 10
        long_period  : 长期均线周期，如 30
        ma_type      : 均线类型，'sma'（简单）或 'ema'（指数）

    返回：
        pd.Series，值域 {1, -1, 0}
            1  = 金叉当根，触发买入
           -1  = 死叉当根，触发卖出
            0  = 无操作

    信号生成逻辑（关键代码）：
        short_ma  : 短期均线值
        long_ma   : 长期均线值
        cross_up  = (short_ma > long_ma) & (short_ma.shift(1) <= long_ma.shift(1))
        cross_down= (short_ma < long_ma) & (short_ma.shift(1) >= long_ma.shift(1))
    """
    result = df.copy()

    if ma_type == "ema":
        result = ema(result, short_period)
        result = ema(result, long_period)
        short_col = f"ema_{short_period}"
        long_col = f"ema_{long_period}"
    else:
        result = sma(result, short_period)
        result = sma(result, long_period)
        short_col = f"sma_{short_period}"
        long_col = f"sma_{long_period}"

    short_ma = result[short_col]
    long_ma = result[long_col]

    # 金叉：本根短均线 > 长均线，上根短均线 <= 长均线
    cross_up = (short_ma > long_ma) & (short_ma.shift(1) <= long_ma.shift(1))
    # 死叉：本根短均线 < 长均线，上根短均线 >= 长均线
    cross_down = (short_ma < long_ma) & (short_ma.shift(1) >= long_ma.shift(1))

    signals = pd.Series(0, index=df.index)
    signals[cross_up] = 1
    signals[cross_down] = -1

    return signals


def ma_trend_signal(
    df: pd.DataFrame,
    short_period: int = 10,
    long_period: int = 30,
) -> pd.Series:
    """
    均线趋势持仓信号（与 ma_cross_signal 不同：持续持仓版本）

    逻辑：
        短均线 > 长均线时全程持仓（信号=1）
        短均线 < 长均线时全程空仓（信号=0）
        穿越点触发切换

    适合趋势明显的行情，减少震荡中频繁买卖。
    """
    result = df.copy()
    result = sma(result, short_period)
    result = sma(result, long_period)

    short_col = f"sma_{short_period}"
    long_col = f"sma_{long_period}"

    short_ma = result[short_col]
    long_ma = result[long_col]

    cross_up = (short_ma > long_ma) & (short_ma.shift(1) <= long_ma.shift(1))
    cross_down = (short_ma < long_ma) & (short_ma.shift(1) >= long_ma.shift(1))

    signals = pd.Series(0, index=df.index)
    signals[cross_up] = 1
    signals[cross_down] = -1
    return signals


# ──────────────────────────────────────────────────────────
# 直接运行：均线交叉策略回测
# ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    SYMBOL = "BTC/USDT"
    TIMEFRAME = "1d"
    LIMIT = 500
    SHORT_PERIOD = 10     # 短期均线周期
    LONG_PERIOD = 30      # 长期均线周期
    INITIAL_CAPITAL = 10000.0
    COMMISSION = 0.001    # 0.1% 手续费

    print("=" * 60)
    print("均线交叉策略（MA Cross）- 回测")
    print("=" * 60)
    print(f"""
策略说明：
  交易对  : {SYMBOL}
  K线周期 : {TIMEFRAME}
  短期均线 : SMA({SHORT_PERIOD})
  长期均线 : SMA({LONG_PERIOD})
  初始资金 : ${INITIAL_CAPITAL:,.0f} USDT
  手续费   : {COMMISSION*100:.2f}%（单边）

信号规则：
  买入 : SMA({SHORT_PERIOD}) 上穿 SMA({LONG_PERIOD})（金叉）
  卖出 : SMA({SHORT_PERIOD}) 下穿 SMA({LONG_PERIOD})（死叉）
    """)

    print(f"正在从币安获取 {SYMBOL} {TIMEFRAME} 数据...")
    df = load_binance_data(SYMBOL, TIMEFRAME, limit=LIMIT)
    print(f"获取到 {len(df)} 根K线，{df.index[0].date()} → {df.index[-1].date()}")

    # 计算并展示均线
    df_with_ma = sma(sma(df, SHORT_PERIOD), LONG_PERIOD)
    print(f"\n最新5根K线均线值：")
    print(
        df_with_ma[["close", f"sma_{SHORT_PERIOD}", f"sma_{LONG_PERIOD}"]].tail(5).to_string(
            float_format=lambda x: f"${x:,.2f}"
        )
    )

    # 生成信号并统计
    signals = ma_cross_signal(df, SHORT_PERIOD, LONG_PERIOD)
    buy_count = (signals == 1).sum()
    sell_count = (signals == -1).sum()
    print(f"\n信号统计：金叉 {buy_count} 次，死叉 {sell_count} 次")

    # 执行回测
    def strategy_func(df):
        return ma_cross_signal(df, SHORT_PERIOD, LONG_PERIOD)

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

    # 与买入持有基准对比
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
    if alpha > 0:
        print("  结论：均线策略跑赢市场基准")
    else:
        print("  结论：均线策略未能跑赢市场基准（但风险控制可能更好）")
