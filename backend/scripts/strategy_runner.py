"""
自动化策略循环运行器（Strategy Runner）
============================================================
功能：
  每隔一个 K 线周期自动执行：
    1. 从 Binance 拉取最新 K 线数据
    2. 计算技术指标，生成策略信号
    3. 若有买入/卖出信号 → 调用后端 API 执行模拟交易
    4. 输出实时账户状态（余额/持仓/盈亏）

支持策略：
    --strategy ma    均线交叉（默认 SMA 10/30）
    --strategy rsi   RSI 超买超卖（默认 14 期，30/70）
    --strategy boll  布林带均值回归（默认 20 期，2 倍标准差）

使用方式（在 backend 目录下运行，需先启动后端服务）：
    python scripts/strategy_runner.py
    python scripts/strategy_runner.py --strategy rsi --symbol ETHUSDT --interval 1h
    python scripts/strategy_runner.py --strategy boll --symbol BTCUSDT --interval 4h --dry-run

参数说明：
    --symbol    交易对（默认 BTCUSDT）
    --interval  K线周期，如 1m/5m/15m/1h/4h/1d（默认 1h）
    --strategy  策略类型：ma/rsi/boll（默认 ma）
    --capital   每次买入金额 USDT（默认 1000，-1 表示全仓）
    --api-url   后端 API 地址（默认 http://localhost:8000）
    --dry-run   演练模式：只打印信号，不实际下单
    --lookback  计算指标需要的历史 K 线数（默认 200）
    --once      只运行一次然后退出（调试用）
"""

import asyncio
import sys
import os
import argparse
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.binance_service import BinanceService
from strategy_indicators import sma, ema, bollinger_bands, rsi as calc_rsi

# ──────────────────────────────────────────────────────────
# 日志配置
# ──────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("StrategyRunner")


# ──────────────────────────────────────────────────────────
# K 线周期 → 秒数 映射（用于计算等待时间）
# ──────────────────────────────────────────────────────────

INTERVAL_SECONDS = {
    "1m":   60,
    "3m":   180,
    "5m":   300,
    "15m":  900,
    "30m":  1800,
    "1h":   3600,
    "2h":   7200,
    "4h":   14400,
    "6h":   21600,
    "8h":   28800,
    "12h":  43200,
    "1d":   86400,
    "1w":   604800,
}


# ──────────────────────────────────────────────────────────
# 策略信号函数
# ──────────────────────────────────────────────────────────

def ma_signal(df: pd.DataFrame, short: int = 10, long: int = 30) -> int:
    """
    均线交叉策略
    返回：1=买入, -1=卖出, 0=持仓不变
    """
    df = sma(sma(df, short), long)
    s = df[f"sma_{short}"]
    l = df[f"sma_{long}"]
    # 最后两根K线判断是否发生交叉
    if len(df) < long + 2:
        return 0
    if s.iloc[-1] > l.iloc[-1] and s.iloc[-2] <= l.iloc[-2]:
        return 1   # 金叉
    if s.iloc[-1] < l.iloc[-1] and s.iloc[-2] >= l.iloc[-2]:
        return -1  # 死叉
    return 0


def rsi_signal(df: pd.DataFrame, period: int = 14, oversold: float = 30, overbought: float = 70) -> int:
    """
    RSI 超买超卖策略
    """
    df = calc_rsi(df, period)
    rv = df[f"rsi_{period}"]
    if len(rv) < period + 2:
        return 0
    if rv.iloc[-1] > oversold and rv.iloc[-2] <= oversold:
        return 1   # 从超卖区回升
    if rv.iloc[-1] < overbought and rv.iloc[-2] >= overbought:
        return -1  # 从超买区回落
    return 0


def boll_signal(df: pd.DataFrame, period: int = 20, std_dev: float = 2.0) -> int:
    """
    布林带均值回归策略
    """
    df = bollinger_bands(df, period, std_dev)
    pb = df["boll_pct_b"]
    if len(pb) < period + 2:
        return 0
    if pb.iloc[-1] > 0.0 and pb.iloc[-2] <= 0.0:
        return 1   # 价格从下轨下方回升
    if pb.iloc[-1] < 1.0 and pb.iloc[-2] >= 1.0:
        return -1  # 价格从上轨上方回落
    return 0


SIGNAL_FUNCS = {
    "ma":   ma_signal,
    "rsi":  rsi_signal,
    "boll": boll_signal,
}

SIGNAL_NAMES = {1: "买入 ▲", -1: "卖出 ▼", 0: "持仓  ─"}


# ──────────────────────────────────────────────────────────
# 后端 API 客户端
# ──────────────────────────────────────────────────────────

class TradingAPIClient:
    """与后端 Paper Trading API 交互"""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip("/")

    async def get_account(self) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{self.base_url}/api/v1/trading/account")
            r.raise_for_status()
            return r.json()

    async def get_positions(self) -> list:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{self.base_url}/api/v1/trading/positions")
            r.raise_for_status()
            return r.json().get("positions", [])

    async def create_order(self, symbol: str, side: str, quantity: float) -> dict:
        """
        提交模拟订单。symbol 格式为 "BTCUSDT"（不含斜杠）。
        """
        payload = {"symbol": symbol, "side": side, "quantity": quantity, "order_type": "MARKET"}
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(f"{self.base_url}/api/v1/trading/order", json=payload)
            r.raise_for_status()
            return r.json()

    async def get_orders(self, limit: int = 5) -> list:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{self.base_url}/api/v1/trading/orders?limit={limit}")
            r.raise_for_status()
            return r.json().get("orders", [])


# ──────────────────────────────────────────────────────────
# 主循环
# ──────────────────────────────────────────────────────────

async def run_loop(
    symbol_ccxt: str,        # 如 "BTC/USDT"
    symbol_clean: str,       # 如 "BTCUSDT"
    interval: str,
    strategy: str,
    trade_amount: float,     # 每次买入的 USDT 金额，-1 = 全仓
    api_url: str,
    dry_run: bool,
    lookback: int,
    run_once: bool,
):
    binance  = BinanceService()
    api      = TradingAPIClient(api_url)
    signal_f = SIGNAL_FUNCS[strategy]
    interval_sec = INTERVAL_SECONDS.get(interval, 3600)

    logger.info(f"策略运行器启动")
    logger.info(f"  交易对   : {symbol_clean}")
    logger.info(f"  K线周期  : {interval}（{interval_sec}秒）")
    logger.info(f"  策略     : {strategy.upper()}")
    logger.info(f"  买入金额 : {'全仓' if trade_amount == -1 else f'${trade_amount:.0f} USDT'}")
    logger.info(f"  演练模式 : {'是（不下单）' if dry_run else '否（实际模拟下单）'}")
    logger.info("-" * 50)

    iteration = 0

    while True:
        iteration += 1
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"\n{'='*50}")
        logger.info(f"第 {iteration} 次检查  {now}")

        # ── 1. 获取最新 K 线 ──
        try:
            df = await binance.get_klines_dataframe(symbol_ccxt, interval, limit=lookback)
            logger.info(f"K线数据: {len(df)} 根  最新收盘价 ${df['close'].iloc[-1]:,.2f}")
        except Exception as e:
            logger.error(f"获取 K 线失败: {e}")
            if run_once:
                break
            await asyncio.sleep(60)
            continue

        # ── 2. 生成策略信号 ──
        try:
            signal = signal_f(df)
        except Exception as e:
            logger.error(f"信号计算失败: {e}")
            signal = 0

        signal_text = SIGNAL_NAMES.get(signal, "未知")
        logger.info(f"策略信号: {signal_text}")

        # ── 3. 打印当前技术指标（辅助参考）──
        _log_indicators(df, strategy)

        # ── 4. 执行交易 ──
        current_price = float(df["close"].iloc[-1])

        if signal != 0 and not dry_run:
            try:
                # 查询当前账户状态
                account   = await api.get_account()
                positions = await api.get_positions()

                available_usdt  = account.get("available_balance", 0)
                has_position    = any(p["symbol"] == symbol_clean for p in positions)
                pos_qty         = next((p["quantity"] for p in positions if p["symbol"] == symbol_clean), 0)

                if signal == 1 and not has_position:
                    # 计算买入数量
                    amount = available_usdt if trade_amount == -1 else min(trade_amount, available_usdt)
                    if amount < 10:
                        logger.warning(f"余额不足（${available_usdt:.2f} USDT），跳过买入")
                    else:
                        qty = amount / current_price
                        logger.info(f"执行买入: {qty:.6f} {symbol_clean.replace('USDT','')} @ ${current_price:,.2f}")
                        order = await api.create_order(symbol_clean, "BUY", qty)
                        logger.info(f"订单成功: {order.get('order_id')}  手续费 ${order.get('fee',0):.4f}")

                elif signal == -1 and has_position and pos_qty > 0:
                    logger.info(f"执行卖出: {pos_qty:.6f} {symbol_clean.replace('USDT','')} @ ${current_price:,.2f}")
                    order = await api.create_order(symbol_clean, "SELL", pos_qty)
                    pnl = order.get("pnl")
                    pnl_str = f"{pnl:+.4f} USDT" if pnl is not None else "N/A"
                    logger.info(f"订单成功: {order.get('order_id')}  已实现盈亏 {pnl_str}")
                else:
                    reason = "已有持仓" if signal == 1 else "无持仓可卖"
                    logger.info(f"跳过执行（{reason}）")

            except Exception as e:
                logger.error(f"交易执行失败: {e}")

        elif signal != 0 and dry_run:
            logger.info(f"[演练模式] 信号 {signal_text}，不实际下单")

        # ── 5. 打印账户状态 ──
        if not dry_run:
            await _log_account_status(api, symbol_clean, current_price)

        # ── 6. 计算等待时间到下一根 K 线 ──
        if run_once:
            logger.info("\n[--once 模式] 运行完毕，退出")
            break

        wait = _seconds_to_next_candle(interval_sec)
        logger.info(f"\n等待 {wait:.0f} 秒后检查下一根 K 线... (下次: {_next_candle_time(interval_sec)})")
        await asyncio.sleep(wait)

    await binance.close()


# ──────────────────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────────────────

def _log_indicators(df: pd.DataFrame, strategy: str):
    """打印当前技术指标值"""
    try:
        close = df["close"].iloc[-1]
        if strategy == "ma":
            df2 = sma(sma(df, 10), 30)
            s10 = df2["sma_10"].iloc[-1]
            s30 = df2["sma_30"].iloc[-1]
            logger.info(f"指标参考: 收盘 ${close:,.2f}  SMA10 ${s10:,.2f}  SMA30 ${s30:,.2f}")
        elif strategy == "rsi":
            df2 = calc_rsi(df, 14)
            rv = df2["rsi_14"].iloc[-1]
            status = "超买" if rv > 70 else ("超卖" if rv < 30 else "中性")
            logger.info(f"指标参考: 收盘 ${close:,.2f}  RSI(14) {rv:.1f}（{status}）")
        elif strategy == "boll":
            df2 = bollinger_bands(df, 20, 2.0)
            upper = df2["boll_upper"].iloc[-1]
            mid   = df2["boll_mid"].iloc[-1]
            lower = df2["boll_lower"].iloc[-1]
            pb    = df2["boll_pct_b"].iloc[-1]
            logger.info(f"指标参考: 收盘 ${close:,.2f}  布林带 [{lower:,.0f} / {mid:,.0f} / {upper:,.0f}]  %B={pb:.3f}")
    except Exception:
        pass


async def _log_account_status(api: TradingAPIClient, symbol_clean: str, current_price: float):
    """打印账户余额与持仓状态"""
    try:
        account   = await api.get_account()
        positions = await api.get_positions()
        balance   = account.get("total_balance", 0)
        avail     = account.get("available_balance", 0)

        logger.info(f"\n── 账户状态 ──────────────────")
        logger.info(f"  总余额     : ${balance:,.2f} USDT")
        logger.info(f"  可用余额   : ${avail:,.2f} USDT")

        if positions:
            for pos in positions:
                if pos["symbol"] == symbol_clean:
                    pnl     = pos.get("pnl", 0)
                    pnl_pct = pos.get("pnl_pct", 0)
                    avg     = pos.get("avg_price", 0)
                    qty     = pos.get("quantity", 0)
                    logger.info(f"  持仓 {symbol_clean}: {qty:.6f} 个  均价 ${avg:,.2f}  "
                                f"未实现盈亏 {pnl:+.4f} USDT ({pnl_pct:+.2f}%)")
        else:
            logger.info(f"  当前无持仓")

        # 最近 3 笔成交
        orders = await api.get_orders(limit=3)
        if orders:
            logger.info(f"  最近成交：")
            for o in orders:
                pnl_str = f"  盈亏 {o['pnl']:+.4f}" if o.get("pnl") is not None else ""
                logger.info(f"    {o['created_at'][:19]}  {o['side']} {o['quantity']:.6f} @ ${o['price']:,.2f}{pnl_str}")
    except Exception as e:
        logger.warning(f"账户状态获取失败: {e}")


def _seconds_to_next_candle(interval_sec: int) -> float:
    """计算距离下一根 K 线开始还有多少秒"""
    now = time.time()
    elapsed = now % interval_sec
    remaining = interval_sec - elapsed
    # 提前 5 秒执行（给 API 一点余量）
    return max(remaining - 5, 1)


def _next_candle_time(interval_sec: int) -> str:
    now = time.time()
    next_ts = (int(now / interval_sec) + 1) * interval_sec
    return datetime.fromtimestamp(next_ts).strftime("%H:%M:%S")


# ──────────────────────────────────────────────────────────
# 入口
# ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="自动化策略循环运行器")
    parser.add_argument("--symbol",    type=str,   default="BTCUSDT",              help="交易对（默认 BTCUSDT）")
    parser.add_argument("--interval",  type=str,   default="1h",                   help="K线周期（默认 1h）")
    parser.add_argument("--strategy",  type=str,   default="ma",                   help="策略: ma/rsi/boll（默认 ma）")
    parser.add_argument("--amount",    type=float, default=1000.0,                 help="每次买入金额 USDT，-1=全仓（默认 1000）")
    parser.add_argument("--api-url",   type=str,   default="http://localhost:8000", help="后端 API 地址")
    parser.add_argument("--dry-run",   action="store_true",                        help="演练模式（不下单）")
    parser.add_argument("--lookback",  type=int,   default=200,                    help="历史 K 线数量（默认 200）")
    parser.add_argument("--once",      action="store_true",                        help="只运行一次后退出")
    args = parser.parse_args()

    if args.strategy not in SIGNAL_FUNCS:
        print(f"[错误] 不支持的策略 '{args.strategy}'，可选: {list(SIGNAL_FUNCS.keys())}")
        sys.exit(1)

    if args.interval not in INTERVAL_SECONDS:
        print(f"[错误] 不支持的周期 '{args.interval}'，可选: {list(INTERVAL_SECONDS.keys())}")
        sys.exit(1)

    # 将 BTCUSDT → BTC/USDT
    symbol = args.symbol.upper()
    for quote in ("USDT", "BTC", "ETH", "BNB"):
        if symbol.endswith(quote) and "/" not in symbol:
            symbol_ccxt = f"{symbol[:-len(quote)]}/{quote}"
            break
    else:
        symbol_ccxt = symbol

    asyncio.run(run_loop(
        symbol_ccxt  = symbol_ccxt,
        symbol_clean = args.symbol.upper(),
        interval     = args.interval,
        strategy     = args.strategy,
        trade_amount = args.amount,
        api_url      = args.api_url,
        dry_run      = args.dry_run,
        lookback     = args.lookback,
        run_once     = args.once,
    ))
