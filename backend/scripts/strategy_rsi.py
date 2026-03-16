"""
RSI 超买超卖策略（RSI Overbought/Oversold Strategy）
============================================================
策略原理：
    RSI（Relative Strength Index，相对强弱指数）由 J. Welles Wilder
    于 1978 年提出，衡量一段时间内价格上涨力量与下跌力量的比值。

    【计算步骤】
    1. 计算每日涨跌：delta = Close(t) - Close(t-1)
    2. 分离涨量/跌量：
       gain = max(delta, 0)
       loss = max(-delta, 0)
    3. 用 EMA 平滑（Wilder 平滑，等同于 com=period-1 的 EWM）：
       avg_gain = EMA(gain, period)
       avg_loss = EMA(loss, period)
    4. 相对强弱：RS = avg_gain / avg_loss
    5. RSI = 100 - 100 / (1 + RS)

    RSI 值域：0 ~ 100
        RSI > 70 : 超买（Overbought）—— 涨势过猛，可能反转下跌 → 卖出
        RSI < 30 : 超卖（Oversold）——  跌势过猛，可能反弹上涨 → 买入
        RSI = 50 : 多空均衡线，RSI 持续 > 50 表示多头占优

    【RSI 背离（Divergence）—— 更高级信号】
    顶背离：价格创新高，但 RSI 未创新高 → 上涨动能减弱，看跌
    底背离：价格创新低，但 RSI 未创新低 → 下跌动能减弱，看涨

    【RSI 策略变种】
    1. 经典超买超卖：>70 卖，<30 买（本文 strategy 1）
    2. RSI 中轴穿越：上穿 50 买，下穿 50 卖（本文 strategy 2）
    3. RSI + 布林带组合：RSI 超卖 且 价格触碰布林带下轨 → 更强买入信号

    策略局限：
        - 在强趋势行情中，RSI 可能长期处于超买/超卖区
        - 单独使用胜率不高，需配合趋势过滤
        - 时间周期越短，假信号越多
"""

import sys
import os
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy_indicators import rsi, bollinger_bands
from strategy_backtest import Backtest, load_binance_data


# ──────────────────────────────────────────────────────────
# 信号函数 1：经典 RSI 超买超卖
# ──────────────────────────────────────────────────────────
def rsi_signal(
    df: pd.DataFrame,
    period: int = 14,
    overbought: float = 70.0,
    oversold: float = 30.0,
) -> pd.Series:
    """
    RSI 超买超卖信号

    参数：
        df          : OHLCV DataFrame
        period      : RSI 计算周期，通常取 14
        overbought  : 超买阈值，通常取 70
        oversold    : 超卖阈值，通常取 30

    返回：
        pd.Series，值域 {1, -1, 0}

    信号逻辑：
        买入（1）: RSI 从超卖区（< oversold）回升穿越 oversold 线
        卖出（-1）: RSI 从超买区（> overbought）回落穿越 overbought 线

    关键代码：
        rsi_col = f'rsi_{period}'
        rsi_val = result[rsi_col]
        # 从超卖区回升（RSI上穿超卖线）
        cross_up_oversold   = (rsi_val > oversold)  & (rsi_val.shift(1) <= oversold)
        # 从超买区回落（RSI下穿超买线）
        cross_down_overbought = (rsi_val < overbought) & (rsi_val.shift(1) >= overbought)
    """
    result = rsi(df, period)
    rsi_col = f"rsi_{period}"
    rsi_val = result[rsi_col]

    # RSI 上穿超卖线（从超卖区恢复）→ 买入
    cross_up_oversold = (rsi_val > oversold) & (rsi_val.shift(1) <= oversold)
    # RSI 下穿超买线（从超买区回落）→ 卖出
    cross_down_overbought = (rsi_val < overbought) & (rsi_val.shift(1) >= overbought)

    signals = pd.Series(0, index=df.index)
    signals[cross_up_oversold] = 1
    signals[cross_down_overbought] = -1

    return signals


# ──────────────────────────────────────────────────────────
# 信号函数 2：RSI 中轴（50）穿越 —— 趋势跟踪
# ──────────────────────────────────────────────────────────
def rsi_midline_signal(
    df: pd.DataFrame,
    period: int = 14,
    midline: float = 50.0,
) -> pd.Series:
    """
    RSI 中轴穿越信号（趋势确认型）

    逻辑：
        RSI 上穿 50 → 多头趋势确立 → 买入
        RSI 下穿 50 → 空头趋势确立 → 卖出

    适合趋势行情，比超买超卖信号更为稳健，
    但在震荡行情中会频繁来回。
    """
    result = rsi(df, period)
    rsi_col = f"rsi_{period}"
    rsi_val = result[rsi_col]

    cross_up = (rsi_val > midline) & (rsi_val.shift(1) <= midline)
    cross_down = (rsi_val < midline) & (rsi_val.shift(1) >= midline)

    signals = pd.Series(0, index=df.index)
    signals[cross_up] = 1
    signals[cross_down] = -1
    return signals


# ──────────────────────────────────────────────────────────
# 信号函数 3：RSI + 布林带组合 —— 双重确认
# ──────────────────────────────────────────────────────────
def rsi_boll_combo_signal(
    df: pd.DataFrame,
    rsi_period: int = 14,
    oversold: float = 30.0,
    overbought: float = 70.0,
    boll_period: int = 20,
    boll_std: float = 2.0,
) -> pd.Series:
    """
    RSI + 布林带双重确认信号

    逻辑：
        买入：RSI 处于超卖区（< oversold）AND 价格触碰/低于布林带下轨
        卖出：RSI 处于超买区（> overbought）AND 价格触碰/高于布林带上轨

    双重过滤减少假信号，但信号频率也会降低。
    """
    result = rsi(df, rsi_period)
    result = bollinger_bands(result, boll_period, boll_std)

    rsi_col = f"rsi_{rsi_period}"
    rsi_val = result[rsi_col]
    pct_b = result["boll_pct_b"]

    # 双重确认：RSI超卖 且 价格接近/低于下轨
    buy_cond = (rsi_val < oversold) & (pct_b <= 0.1)
    # 双重确认：RSI超买 且 价格接近/高于上轨
    sell_cond = (rsi_val > overbought) & (pct_b >= 0.9)

    # 只在条件首次满足时触发（避免持续触发）
    buy_trigger = buy_cond & ~buy_cond.shift(1).fillna(False).infer_objects(copy=False)
    sell_trigger = sell_cond & ~sell_cond.shift(1).fillna(False).infer_objects(copy=False)

    signals = pd.Series(0, index=df.index)
    signals[buy_trigger] = 1
    signals[sell_trigger] = -1
    return signals


# ──────────────────────────────────────────────────────────
# 直接运行：RSI 策略回测
# ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    SYMBOL = "BTC/USDT"
    TIMEFRAME = "4h"
    LIMIT = 500
    RSI_PERIOD = 14
    OVERBOUGHT = 70.0
    OVERSOLD = 30.0
    INITIAL_CAPITAL = 10000.0
    COMMISSION = 0.001

    print("=" * 60)
    print("RSI 超买超卖策略 - 回测")
    print("=" * 60)
    print(f"""
策略说明：
  交易对   : {SYMBOL}
  K线周期  : {TIMEFRAME}
  RSI 周期 : {RSI_PERIOD}
  超买阈值 : {OVERBOUGHT}
  超卖阈值 : {OVERSOLD}
  初始资金 : ${INITIAL_CAPITAL:,.0f} USDT
  手续费   : {COMMISSION*100:.2f}%（单边）

信号规则：
  买入 : RSI 从 {OVERSOLD} 以下回升穿越 {OVERSOLD}（超卖区恢复）
  卖出 : RSI 从 {OVERBOUGHT} 以上回落穿越 {OVERBOUGHT}（超买区回落）
    """)

    print(f"正在从币安获取 {SYMBOL} {TIMEFRAME} 数据...")
    df = load_binance_data(SYMBOL, TIMEFRAME, limit=LIMIT)
    print(f"获取到 {len(df)} 根K线，{df.index[0].date()} → {df.index[-1].date()}")

    # 展示最新 RSI 值
    df_rsi = rsi(df, RSI_PERIOD)
    rsi_col = f"rsi_{RSI_PERIOD}"
    print(f"\n最新5根K线 RSI({RSI_PERIOD}) 值：")
    print(df_rsi[["close", rsi_col]].tail(5).to_string(
        float_format=lambda x: f"{x:.2f}"
    ))

    current_rsi = df_rsi[rsi_col].iloc[-1]
    print(f"\n当前 RSI({RSI_PERIOD}) = {current_rsi:.2f}")
    if current_rsi > OVERBOUGHT:
        print(f"  → 超买区（>{OVERBOUGHT}），价格可能回调，关注卖出机会")
    elif current_rsi < OVERSOLD:
        print(f"  → 超卖区（<{OVERSOLD}），价格可能反弹，关注买入机会")
    elif current_rsi > 50:
        print(f"  → 多头区域（50~{OVERBOUGHT}），上升动能较强")
    else:
        print(f"  → 空头区域（{OVERSOLD}~50），下跌动能较强")

    # 信号统计
    signals = rsi_signal(df, RSI_PERIOD, OVERBOUGHT, OVERSOLD)
    buy_count = (signals == 1).sum()
    sell_count = (signals == -1).sum()
    print(f"\n信号统计：买入 {buy_count} 次，卖出 {sell_count} 次")

    # ── 策略 1：经典 RSI 超买超卖 ──
    print("\n" + "=" * 60)
    print("策略 1：经典 RSI 超买超卖")
    print("=" * 60)

    def strat1(df):
        return rsi_signal(df, RSI_PERIOD, OVERBOUGHT, OVERSOLD)

    bt1 = Backtest(df, strat1, initial_capital=INITIAL_CAPITAL,
                   commission=COMMISSION, symbol=SYMBOL, timeframe=TIMEFRAME)
    result1 = bt1.run()
    result1.print_summary()
    result1.print_trades()

    # ── 策略 2：RSI 中轴穿越 ──
    print("\n" + "=" * 60)
    print("策略 2：RSI 中轴（50）穿越 —— 趋势跟踪")
    print("=" * 60)

    def strat2(df):
        return rsi_midline_signal(df, RSI_PERIOD)

    bt2 = Backtest(df, strat2, initial_capital=INITIAL_CAPITAL,
                   commission=COMMISSION, symbol=SYMBOL, timeframe=TIMEFRAME)
    result2 = bt2.run()
    result2.print_summary()

    # ── 策略 3：RSI + 布林带双重确认 ──
    print("\n" + "=" * 60)
    print("策略 3：RSI + 布林带双重确认")
    print("=" * 60)

    def strat3(df):
        return rsi_boll_combo_signal(df, RSI_PERIOD, OVERSOLD, OVERBOUGHT)

    bt3 = Backtest(df, strat3, initial_capital=INITIAL_CAPITAL,
                   commission=COMMISSION, symbol=SYMBOL, timeframe=TIMEFRAME)
    result3 = bt3.run()
    result3.print_summary()

    # ── 对比基准 ──
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

    # 汇总对比
    print("\n" + "=" * 60)
    print("三种 RSI 策略对比汇总")
    print("=" * 60)
    print(f"  {'策略':<20} {'总收益':>10} {'年化':>10} {'最大回撤':>10} {'夏普':>8} {'胜率':>8}")
    print("-" * 70)
    for name, r in [
        ("经典超买超卖", result1),
        ("中轴穿越", result2),
        ("RSI+布林带", result3),
        ("买入持有(基准)", bh_result),
    ]:
        print(
            f"  {name:<20} {r.total_return:>+9.2f}% {r.annual_return:>+9.2f}% "
            f"{r.max_drawdown:>9.2f}% {r.sharpe_ratio:>7.3f} {r.win_rate:>7.1f}%"
        )
    print("=" * 60)
    print("\n关键指标说明：")
    print("  最大回撤   : 资产从峰值跌到谷底的最大跌幅，衡量策略的最坏情况")
    print("  夏普比率   : 每承担1单位风险获得的超额收益，>1为良好，>2为优秀")
    print("  胜率       : 盈利交易占总交易的比例，高胜率≠高收益（还需看盈亏比）")
