"""
CoinGecko 筛选标的 → Binance 批量回测脚本
============================================================
流程：
  1. 调用 CoinGecko 获取市值排名 Top N 的币种（含市值、涨跌等基本面信息）
  2. 将 CoinGecko 的 coin_id 映射为 Binance 交易对（如 bitcoin → BTC/USDT）
  3. 逐个币种从 Binance 获取 K 线数据
  4. 对每个币种运行指定策略的回测
  5. 汇总输出排名报告（按总收益率排序）

使用示例：
    python coingecko_batch_backtest.py
    python coingecko_batch_backtest.py --top 20 --strategy rsi --timeframe 4h
"""

import asyncio
import sys
import os
import argparse
import time
from typing import List, Dict, Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.coingecko_service import CoinGeckoService
from app.services.binance_service import BinanceService
from strategy_indicators import sma, ema, bollinger_bands, rsi, macd
from strategy_backtest import Backtest, Trade
import pandas as pd
import numpy as np


# ──────────────────────────────────────────────────────────
# 策略信号函数库
# ──────────────────────────────────────────────────────────

def make_ma_signal(short: int = 10, long: int = 30):
    """均线交叉策略工厂函数"""
    def signal_func(df: pd.DataFrame) -> pd.Series:
        from strategy_indicators import sma as _sma
        df2 = _sma(_sma(df, short), long)
        s = df2[f"sma_{short}"]
        l = df2[f"sma_{long}"]
        cross_up   = (s > l) & (s.shift(1) <= l.shift(1))
        cross_down = (s < l) & (s.shift(1) >= l.shift(1))
        sig = pd.Series(0, index=df.index)
        sig[cross_up]   = 1
        sig[cross_down] = -1
        return sig
    signal_func.__name__ = f"MA({short}/{long})"
    return signal_func


def make_rsi_signal(period: int = 14, oversold: float = 30, overbought: float = 70):
    """RSI 超买超卖策略工厂函数"""
    def signal_func(df: pd.DataFrame) -> pd.Series:
        from strategy_indicators import rsi as _rsi
        df2 = _rsi(df, period)
        rv = df2[f"rsi_{period}"]
        buy  = (rv > oversold)    & (rv.shift(1) <= oversold)
        sell = (rv < overbought)  & (rv.shift(1) >= overbought)
        sig = pd.Series(0, index=df.index)
        sig[buy]  = 1
        sig[sell] = -1
        return sig
    signal_func.__name__ = f"RSI({period},{oversold}/{overbought})"
    return signal_func


def make_boll_signal(period: int = 20, std_dev: float = 2.0):
    """布林带均值回归策略工厂函数"""
    def signal_func(df: pd.DataFrame) -> pd.Series:
        from strategy_indicators import bollinger_bands as _boll
        df2 = _boll(df, period, std_dev)
        pb  = df2["boll_pct_b"]
        buy  = (pb > 0.0) & (pb.shift(1) <= 0.0)
        sell = (pb < 1.0) & (pb.shift(1) >= 1.0)
        sig = pd.Series(0, index=df.index)
        sig[buy]  = 1
        sig[sell] = -1
        return sig
    signal_func.__name__ = f"BOLL({period},{std_dev})"
    return signal_func


STRATEGY_MAP = {
    "ma":   make_ma_signal,
    "rsi":  make_rsi_signal,
    "boll": make_boll_signal,
}


# ──────────────────────────────────────────────────────────
# CoinGecko ID → Binance 交易对 映射
# ──────────────────────────────────────────────────────────

def coingecko_id_to_binance_symbol(coin_id: str, symbol: str) -> Optional[str]:
    """
    将 CoinGecko coin_id / symbol 转换为 Binance USDT 交易对。
    返回 None 表示该币种在 Binance 上无 USDT 对（跳过）。
    """
    # 稳定币和无法交易的币种
    SKIP_SYMBOLS = {"USDT", "USDC", "BUSD", "DAI", "TUSD", "USDP", "FRAX", "GUSD"}
    s = symbol.upper()
    if s in SKIP_SYMBOLS:
        return None
    return f"{s}/USDT"


# ──────────────────────────────────────────────────────────
# 单币种回测
# ──────────────────────────────────────────────────────────

def run_single_backtest(
    df: pd.DataFrame,
    symbol: str,
    strategy_name: str,
    signal_func,
    initial_capital: float = 10000.0,
    commission: float = 0.001,
    timeframe: str = "1d",
) -> Optional[Dict[str, Any]]:
    """对单个 DataFrame 运行回测，返回结果字典"""
    if df is None or len(df) < 300:
        print(f"⚠️  {symbol}: 数据不足（{len(df) if df is not None else 0} 根 < 300 根），跳过")
        return None
    try:
        bt = Backtest(
            df, signal_func,
            initial_capital=initial_capital,
            commission=commission,
            symbol=symbol,
            timeframe=timeframe,
        )
        result = bt.run()
        return {
            "symbol":        symbol,
            "strategy":      strategy_name,
            "timeframe":     timeframe,
            "n_candles":     len(df),
            "total_return":  result.total_return,
            "annual_return": result.annual_return,
            "max_drawdown":  result.max_drawdown,
            "sharpe_ratio":  result.sharpe_ratio,
            "win_rate":      result.win_rate,
            "profit_factor": result.profit_factor,
            "total_trades":  result.total_trades,
        }
    except Exception as e:
        print(f"  [警告] {symbol} 回测失败: {e}")
        return None


# ──────────────────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────────────────

async def main(
    top_n: int = 10,
    strategy: str = "ma",
    timeframe: str = "1d",
    limit: int = 500,
    initial_capital: float = 10000.0,
):
    print("=" * 70)
    print("CoinGecko 筛选标的 → Binance 批量回测")
    print("=" * 70)
    print(f"  筛选范围  : CoinGecko 市值 Top {top_n}")
    print(f"  策略      : {strategy.upper()}")
    print(f"  K线周期   : {timeframe}")
    print(f"  K线数量   : {limit} 根")
    print(f"  初始资金  : ${initial_capital:,.0f} USDT")
    print()

    # ── Step 1: CoinGecko 获取 Top N 市值币种 ──
    print("Step 1 | 从 CoinGecko 获取市值排名...")
    cg = CoinGeckoService()
    try:
        markets = cg.get_market_overview(per_page=top_n + 10)  # 多取一些，过滤稳定币后仍有 top_n
    except Exception as e:
        print(f"[错误] CoinGecko 请求失败: {e}")
        return

    # 过滤稳定币，最终取 top_n 个
    candidates = []
    for m in markets:
        symbol = m.symbol.upper()
        binance_sym = coingecko_id_to_binance_symbol(m.id, symbol)
        if binance_sym is None:
            continue
        candidates.append({
            "rank":        m.market_cap_rank,
            "name":        m.name,
            "coin_id":     m.id,
            "symbol":      symbol,
            "binance_sym": binance_sym,
            "market_cap":  m.market_cap or 0,
            "change_24h":  m.price_change_percentage_24h or 0,
            "price":       m.current_price,
        })
        if len(candidates) >= top_n:
            break

    print(f"  筛选出 {len(candidates)} 个候选币种（已排除稳定币）\n")
    print(f"  {'排名':<5} {'名称':<18} {'交易对':<12} {'市值':<20} {'24h':<10}")
    print("  " + "-" * 68)
    for c in candidates:
        mc = f"${c['market_cap']:,.0f}" if c['market_cap'] else "N/A"
        ch = f"{c['change_24h']:+.2f}%"
        print(f"  #{c['rank']:<4} {c['name']:<18} {c['binance_sym']:<12} {mc:<20} {ch:<10}")

    # ── Step 2: Binance 获取 K 线并回测 ──
    print(f"\nStep 2 | 从 Binance 获取 K 线并运行 {strategy.upper()} 策略回测...")
    binance = BinanceService()
    signal_func = STRATEGY_MAP[strategy]()
    strategy_name = getattr(signal_func, "__name__", strategy)

    results = []
    for i, c in enumerate(candidates):
        sym = c["binance_sym"]
        print(f"  [{i+1}/{len(candidates)}] {sym} ...", end=" ", flush=True)
        try:
            df = await binance.get_klines_dataframe(sym, timeframe, limit=limit)
            res = run_single_backtest(
                df, sym, strategy_name, signal_func,
                initial_capital, 0.001, timeframe,
            )
            if res:
                # 附加 CoinGecko 基本面信息
                res["rank"]       = c["rank"]
                res["name"]       = c["name"]
                res["market_cap"] = c["market_cap"]
                res["change_24h"] = c["change_24h"]
                results.append(res)
                flag = "✅" if res["total_return"] >= 0 else "❌"
                print(f"{flag}  收益 {res['total_return']:+.2f}%  夏普 {res['sharpe_ratio']:.2f}  交易 {res['total_trades']}笔")
            else:
                print("跳过（数据不足）")
        except Exception as e:
            print(f"失败: {e}")

        # CoinGecko 免费 API 限速保护（30次/分钟）
        time.sleep(0.3)

    if not results:
        print("\n没有有效回测结果")
        return

    # ── Step 3: 汇总报告 ──
    results.sort(key=lambda x: x["total_return"], reverse=True)

    print("\n" + "=" * 70)
    print(f"  批量回测汇总报告  策略: {strategy_name}  周期: {timeframe}")
    print("=" * 70)
    print(f"  {'排名':<4} {'交易对':<12} {'名称':<16} {'总收益':>9} {'年化':>9} {'最大回撤':>9} {'夏普':>7} {'胜率':>7} {'交易':>5}")
    print("  " + "-" * 80)

    for rank, r in enumerate(results, 1):
        ret_color = "+" if r["total_return"] >= 0 else ""
        print(
            f"  {rank:<4} {r['symbol']:<12} {r['name'][:15]:<16} "
            f"{ret_color}{r['total_return']:>8.2f}% "
            f"{r['annual_return']:>+8.2f}% "
            f"{r['max_drawdown']:>8.2f}% "
            f"{r['sharpe_ratio']:>6.3f} "
            f"{r['win_rate']:>6.1f}% "
            f"{r['total_trades']:>5}"
        )

    # 统计摘要
    avg_return  = sum(r["total_return"]  for r in results) / len(results)
    avg_sharpe  = sum(r["sharpe_ratio"]  for r in results) / len(results)
    best        = results[0]
    worst       = results[-1]

    print("=" * 70)
    print(f"\n  统计摘要：")
    print(f"    平均收益率   : {avg_return:+.2f}%")
    print(f"    平均夏普比率 : {avg_sharpe:.3f}")
    print(f"    最佳标的     : {best['symbol']} ({best['total_return']:+.2f}%)")
    print(f"    最差标的     : {worst['symbol']} ({worst['total_return']:+.2f}%)")
    print(f"    正收益数量   : {sum(1 for r in results if r['total_return'] > 0)}/{len(results)}")

    print("\n  说明：")
    print("    - 回测结果仅供参考，历史表现不代表未来收益")
    print("    - 市值信息来自 CoinGecko，K线数据来自 Binance")
    print("    - 建议结合基本面（市值/流通量/项目进展）综合判断")

    await binance.close()


# ──────────────────────────────────────────────────────────
# 入口
# ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CoinGecko 筛选标的 → Binance 批量回测")
    parser.add_argument("--top",      type=int,   default=10,      help="CoinGecko 市值排名 Top N（默认 10）")
    parser.add_argument("--strategy", type=str,   default="ma",    help="策略: ma / rsi / boll（默认 ma）")
    parser.add_argument("--timeframe",type=str,   default="1d",    help="K线周期: 1h / 4h / 1d（默认 1d）")
    parser.add_argument("--limit",    type=int,   default=500,     help="K线数量（默认 500）")
    parser.add_argument("--capital",  type=float, default=10000.0, help="初始资金 USDT（默认 10000）")
    args = parser.parse_args()

    if args.strategy not in STRATEGY_MAP:
        print(f"[错误] 不支持的策略 '{args.strategy}'，可选: {list(STRATEGY_MAP.keys())}")
        sys.exit(1)

    asyncio.run(main(
        top_n=args.top,
        strategy=args.strategy,
        timeframe=args.timeframe,
        limit=args.limit,
        initial_capital=args.capital,
    ))
