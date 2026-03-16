"""
回测引擎核心 - 量化策略历史模拟验证框架 (Event-Driven)
============================================================
v2.0 升级特性：
    - 事件驱动撮合：防前视偏差 (Signal at Close -> Trade at Next Open)
    - 双向交易支持：支持做多 (Long) 与 做空 (Short)
    - 动态滑点模型：基于 ATR 与 市场冲击 (Square Root Law)
    - 资金费率模拟：支持永续合约资金费率扣除
    - 完善的成交记录：包含滑点成本与手续费明细

核心假设：
    - 信号在 k 线收盘时产生，于下一根 k 线开盘时以市价单成交
    - 资金费率每 8 小时收取一次 (模拟)
"""

import sys
import os
import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Dict
from enum import Enum

# 引入指标计算
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.strategy_indicators import atr

# ──────────────────────────────────────────────────────────
# 常量与枚举
# ──────────────────────────────────────────────────────────
class Side(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NONE = "NONE"

class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"

# ──────────────────────────────────────────────────────────
# 数据结构
# ──────────────────────────────────────────────────────────
@dataclass
class Trade:
    """单笔交易记录 (Round-trip)"""
    symbol: str
    side: Side                 # LONG or SHORT
    entry_time: pd.Timestamp   # 开仓时间
    exit_time: pd.Timestamp    # 平仓时间
    entry_price: float         # 开仓均价
    exit_price: float          # 平仓均价
    quantity: float            # 数量
    pnl: float                 # 净盈亏 (扣除手续费、滑点、资金费)
    pnl_pct: float             # 收益率 %
    commission: float          # 手续费总额
    slippage: float            # 滑点损耗总额
    funding_fee: float         # 资金费总额
    holding_period: int        # 持仓周期 (Bar 数)

@dataclass
class BacktestConfig:
    """回测配置"""
    initial_capital: float = 100000.0
    commission_rate: float = 0.0005    # 万5
    slippage_factor: float = 0.5       # ATR 倍数
    impact_factor: float = 0.1         # 冲击系数
    daily_volume: float = 100_000_000  # 模拟日成交量 (用于冲击模型)
    funding_rate_8h: float = 0.0001    # 万1 资金费率 (每8小时)
    enable_shorting: bool = True       # 是否允许做空

@dataclass
class BacktestResult:
    """回测结果"""
    config: BacktestConfig
    symbol: str
    timeframe: str
    start_time: pd.Timestamp
    end_time: pd.Timestamp
    
    final_capital: float
    total_return: float
    annual_return: float
    max_drawdown: float
    sharpe_ratio: float
    win_rate: float
    profit_factor: float
    total_trades: int
    
    # TCA Metrics
    total_slippage: float
    total_commission: float
    avg_slippage_pct: float
    
    trades: List[Trade]
    equity_curve: pd.Series
    drawdown_curve: pd.Series
    
    def print_summary(self):
        print("\n" + "=" * 60)
        print(f"  回测结果摘要 (v2.0)  {self.symbol} {self.timeframe}")
        print("=" * 60)
        print(f"  回测区间   : {self.start_time.date()} → {self.end_time.date()}")
        print(f"  初始资金   : ${self.config.initial_capital:,.2f}")
        print(f"  最终资金   : ${self.final_capital:,.2f}")
        print(f"  总收益率   : {self.total_return:+.2f}%")
        print(f"  年化收益率 : {self.annual_return:+.2f}%")
        print(f"  最大回撤   : {self.max_drawdown:.2f}%")
        print(f"  夏普比率   : {self.sharpe_ratio:.3f}")
        print("-" * 60)
        print(f"  总交易次数 : {self.total_trades}")
        print(f"  胜率       : {self.win_rate:.1f}%")
        print(f"  盈亏比     : {self.profit_factor:.2f}")
        print("-" * 60)
        print(f"  [TCA] 总滑点损耗 : ${self.total_slippage:,.2f}")
        print(f"  [TCA] 总手续费   : ${self.total_commission:,.2f}")
        print(f"  [TCA] 平均滑点 % : {self.avg_slippage_pct*100:.4f}%")
        print("=" * 60)

# ──────────────────────────────────────────────────────────
# 回测引擎
# ──────────────────────────────────────────────────────────
class Backtest:
    def __init__(
        self,
        df: pd.DataFrame,
        strategy_func: Callable[[pd.DataFrame], pd.Series],
        config: BacktestConfig = BacktestConfig(),
        symbol: str = "BTC/USDT",
        timeframe: str = "1d"
    ):
        self.df = df.copy()
        self.strategy_func = strategy_func
        self.config = config
        self.symbol = symbol
        self.timeframe = timeframe
        
        # 预计算 ATR 用于滑点模型
        if 'high' in self.df.columns and 'low' in self.df.columns and 'close' in self.df.columns:
            self.df = atr(self.df, period=14)
            self.df['atr_14'] = self.df['atr_14'].fillna(0)
        else:
            self.df['atr_14'] = 0.0

    def run(self) -> BacktestResult:
        # 1. 生成信号
        # 约定：1=Target Long, -1=Target Short, 0=Target Flat
        signals = self.strategy_func(self.df)
        
        # 2. 初始化状态
        capital = self.config.initial_capital
        position_qty = 0.0
        position_avg_price = 0.0
        position_side = Side.NONE
        position_entry_time = None
        
        trades: List[Trade] = []
        equity_curve = []
        
        # 资金费率计时器
        last_funding_time = self.df.index[0]
        
        # 3. 事件循环
        # 遍历每一根 K 线
        # 逻辑：
        #   T时刻收盘：计算信号
        #   T+1时刻开盘：执行信号 (Open Price)
        
        # 为了模拟 T+1 执行，我们维护一个 target_position
        target_side = Side.NONE
        
        # 转换为 numpy 数组加速
        opens = self.df['open'].values
        closes = self.df['close'].values
        highs = self.df['high'].values
        lows = self.df['low'].values
        atrs = self.df['atr_14'].values
        times = self.df.index
        sigs = signals.values
        
        n = len(self.df)
        
        for i in range(n):
            current_time = times[i]
            current_open = opens[i]
            current_close = closes[i]
            current_atr = atrs[i] if i < len(atrs) else 0
            
            # --- A. 撮合/执行 (在当前 Bar 开盘时执行上一个 Bar 产生的信号) ---
            # 只有 i > 0 才能执行 i-1 的信号
            
            # 计算滑点 (ATR Slippage + Market Impact)
            # Impact Model: Square Root Law
            # Impact = sigma * sqrt(Order Size / Daily Volume)
            # We approximate sigma with ATR/Price
            
            # Estimate Order Size for Impact Calculation
            # If holding position, we might close or flip (size ~= position_value or 2*position_value)
            # If flat, we might open (size ~= capital)
            # We use a conservative estimate: max(equity, capital)
            # Since we track capital as 'available cash', we need to estimate equity.
            
            est_equity = capital
            if position_qty != 0:
                if position_side == Side.LONG:
                    est_equity += position_qty * current_open
                else:
                    est_equity += position_qty * (2 * position_avg_price - current_open)
            
            # Ensure non-negative for sqrt
            est_order_size = max(0.0, est_equity)
            
            participation_rate = est_order_size / self.config.daily_volume
            
            # Impact Cost % = Impact Factor * Volatility * sqrt(Participation Rate)
            # This is a variant. Standard Square Root Law: Cost = Y * sigma * sqrt(X/V)
            # Here config.impact_factor is Y.
            volatility_pct = (current_atr / current_open) if current_open > 0 else 0
            market_impact_pct = self.config.impact_factor * volatility_pct * np.sqrt(participation_rate)
            
            # Base spread/volatility slippage
            volatility_slip_pct = volatility_pct * self.config.slippage_factor
            
            total_slip_pct = volatility_slip_pct + market_impact_pct
            
            executed_price = current_open
            
            # 资金费率结算 (每8小时)
            if (current_time - last_funding_time).total_seconds() >= 8*3600:
                if position_qty != 0:
                    funding = abs(position_qty) * current_open * self.config.funding_rate_8h
                    if position_side == Side.LONG:
                        capital -= funding # 多头付钱
                    else:
                        # 简化的资金费率模型：空头收钱（或付钱，取决于费率正负）
                        # 这里假设费率为正，多头付给空头
                        capital += funding 
                    
                    # 记录资金费成本（可选，暂不计入 Trade 明细，直接影响 Capital）
                last_funding_time = current_time

            # 检查是否需要调仓
            # target_side 来自上一个 Bar 的信号
            
            # 动作判断
            action = "HOLD"
            if target_side == Side.LONG:
                if position_side == Side.NONE: action = "OPEN_LONG"
                elif position_side == Side.SHORT: action = "FLIP_TO_LONG"
            elif target_side == Side.SHORT:
                if self.config.enable_shorting:
                    if position_side == Side.NONE: action = "OPEN_SHORT"
                    elif position_side == Side.LONG: action = "FLIP_TO_SHORT"
                else:
                    # 不允许做空，则平多
                    if position_side == Side.LONG: action = "CLOSE_LONG"
            elif target_side == Side.NONE:
                if position_side == Side.LONG: action = "CLOSE_LONG"
                elif position_side == Side.SHORT: action = "CLOSE_SHORT"
            
            # 执行动作
            if action != "HOLD":
                # 平仓逻辑 (CLOSE, FLIP)
                if action in ["CLOSE_LONG", "FLIP_TO_SHORT", "CLOSE_SHORT", "FLIP_TO_LONG"]:
                    # 计算平仓价格 (考虑滑点)
                    # Long Close (Sell) -> Price * (1 - slip)
                    # Short Close (Buy) -> Price * (1 + slip)
                    
                    exit_price = current_open
                    slip_cost = 0.0
                    
                    if position_side == Side.LONG:
                        exit_price = current_open * (1 - total_slip_pct)
                        gross_pnl = (exit_price - position_avg_price) * position_qty
                        slip_cost = current_open * total_slip_pct * position_qty
                    else: # SHORT
                        exit_price = current_open * (1 + total_slip_pct)
                        gross_pnl = (position_avg_price - exit_price) * position_qty
                        slip_cost = current_open * total_slip_pct * position_qty
                    
                    commission = exit_price * position_qty * self.config.commission_rate
                    net_pnl = gross_pnl - commission
                    
                    # 记录交易
                    holding_period_bars = i - (times.get_loc(position_entry_time) if position_entry_time in times else 0)
                    
                    trades.append(Trade(
                        symbol=self.symbol,
                        side=position_side,
                        entry_time=position_entry_time,
                        exit_time=current_time,
                        entry_price=position_avg_price,
                        exit_price=exit_price,
                        quantity=position_qty,
                        pnl=net_pnl,
                        pnl_pct=(net_pnl / (position_avg_price * position_qty)) * 100,
                        commission=commission, # 这里只记录平仓手续费，开仓的已扣除
                        slippage=slip_cost,
                        funding_fee=0.0, # TODO: Track accumulative funding per trade
                        holding_period=holding_period_bars
                    ))
                    
                    capital += (position_qty * position_avg_price) + net_pnl if position_side == Side.LONG else \
                               (position_qty * position_avg_price) + net_pnl # Short logic simplified: Margin + PnL
                    
                    # 重置持仓
                    position_qty = 0.0
                    position_avg_price = 0.0
                    position_side = Side.NONE

                # 开仓逻辑 (OPEN, FLIP)
                if action in ["OPEN_LONG", "FLIP_TO_LONG", "OPEN_SHORT", "FLIP_TO_SHORT"]:
                    # 全仓买入
                    if capital > 0:
                        # 开仓价格
                        # Long Open (Buy) -> Price * (1 + slip)
                        # Short Open (Sell) -> Price * (1 - slip)
                        
                        entry_price_exec = current_open
                        
                        if action in ["OPEN_LONG", "FLIP_TO_LONG"]:
                            side = Side.LONG
                            entry_price_exec = current_open * (1 + total_slip_pct)
                        else:
                            side = Side.SHORT
                            entry_price_exec = current_open * (1 - total_slip_pct)
                        
                        # 计算数量 (考虑手续费)
                        # Cost = Qty * Price * (1 + Comm)
                        # Qty = Capital / (Price * (1 + Comm))
                        qty = capital / (entry_price_exec * (1 + self.config.commission_rate))
                        
                        commission = qty * entry_price_exec * self.config.commission_rate
                        capital -= commission # 扣除开仓手续费
                        # 实际上 capital 变成了 Margin (对于 Short) 或 Asset Value (对于 Long)
                        # 简化模型：capital 保持为 Cash，Position 独立跟踪
                        # 这里我们用 Cash Account 模型：Long 消耗 Cash，Short 锁住 Cash 作为 Margin
                        
                        capital -= (qty * entry_price_exec) if side == Side.LONG else (qty * entry_price_exec) # Lock margin
                        
                        position_qty = qty
                        position_avg_price = entry_price_exec
                        position_side = side
                        position_entry_time = current_time

            # --- B. 记录当前权益 (Mark to Market) ---
            current_equity = capital
            if position_side == Side.LONG:
                current_equity += position_qty * current_close
            elif position_side == Side.SHORT:
                # Short Equity = Margin + (Entry - Current) * Qty
                # Margin was locked as (Qty * Entry)
                # So Equity = (Qty * Entry) + (Entry - Current) * Qty = Qty * (2*Entry - Current)
                # Wait, simpler:
                # Equity = Initial_Cash + Realized_PnL + Unrealized_PnL
                # We tracked Capital as "Available Cash".
                # When opening Short, we deducted Qty*Entry from Capital.
                # So Current Equity = Capital (Remaining) + (Qty * Entry) + (Qty * (Entry - Current))
                #                   = Capital + Qty * (2*Entry - Current)
                current_equity += position_qty * (2 * position_avg_price - current_close)
            
            equity_curve.append(current_equity)
            
            # --- C. 更新下一时刻的目标信号 ---
            # i 时刻产生的信号，将在 i+1 时刻执行
            sig = sigs[i]
            if sig == 1: target_side = Side.LONG
            elif sig == -1: target_side = Side.SHORT
            else: target_side = Side.NONE
            
        # 4. 统计结果
        equity_series = pd.Series(equity_curve, index=times)
        
        # 计算回撤
        rolling_max = equity_series.cummax()
        drawdown = (equity_series - rolling_max) / rolling_max
        max_drawdown = abs(drawdown.min()) * 100
        
        # 计算收益
        final_capital = equity_series.iloc[-1]
        total_return = (final_capital / self.config.initial_capital - 1) * 100
        
        # 年化
        days = (times[-1] - times[0]).days
        annual_return = ((1 + total_return/100) ** (365/days) - 1) * 100 if days > 0 else 0
        
        # 夏普
        daily_ret = equity_series.pct_change().dropna()
        sharpe = 0.0
        if daily_ret.std() > 0:
            sharpe = (daily_ret.mean() / daily_ret.std()) * np.sqrt(365)
            
        # 交易统计
        total_trades = len(trades)
        win_rate = len([t for t in trades if t.pnl > 0]) / total_trades * 100 if total_trades > 0 else 0
        avg_win = np.mean([t.pnl for t in trades if t.pnl > 0]) if total_trades > 0 else 0
        avg_loss = abs(np.mean([t.pnl for t in trades if t.pnl < 0])) if total_trades > 0 else 0
        profit_factor = avg_win / avg_loss if avg_loss > 0 else 0
        
        # TCA Stats
        total_slippage = sum(t.slippage for t in trades)
        total_commission = sum(t.commission for t in trades)
        # Average slippage pct per trade (entry+exit combined)
        # Rough calc: sum(slippage) / sum(volume) is better, but here simple avg
        avg_slippage_pct = total_slippage / (self.config.initial_capital * total_trades * 2) if total_trades > 0 else 0
        # Wait, volume changes. Better:
        avg_slippage_pct = np.mean([t.slippage / (t.quantity * t.entry_price * 2) for t in trades]) if total_trades > 0 else 0

        return BacktestResult(
            config=self.config,
            symbol=self.symbol,
            timeframe=self.timeframe,
            start_time=times[0],
            end_time=times[-1],
            final_capital=final_capital,
            total_return=total_return,
            annual_return=annual_return,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe,
            win_rate=win_rate,
            profit_factor=profit_factor,
            total_trades=total_trades,
            total_slippage=total_slippage,
            total_commission=total_commission,
            avg_slippage_pct=avg_slippage_pct,
            trades=trades,
            equity_curve=equity_series,
            drawdown_curve=drawdown
        )

# ──────────────────────────────────────────────────────────
# 演示
# ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    from app.services.binance_service import BinanceService
    import asyncio
    
    async def main():
        print("正在获取数据...")
        service = BinanceService()
        df = await service.get_klines_dataframe("BTC/USDT", "4h", limit=1000)
        await service.close()
        
        # 简单均线策略：SMA20 > SMA60 做多，否则做空
        def ma_strategy(data: pd.DataFrame) -> pd.Series:
            sma20 = data['close'].rolling(20).mean()
            sma60 = data['close'].rolling(60).mean()
            
            # 1=Long, -1=Short
            signals = pd.Series(0, index=data.index)
            signals[sma20 > sma60] = 1
            signals[sma20 < sma60] = -1
            return signals
            
        print("开始回测...")
        bt = Backtest(df, ma_strategy, symbol="BTC/USDT", timeframe="4h")
        result = bt.run()
        result.print_summary()
        
    asyncio.run(main())
