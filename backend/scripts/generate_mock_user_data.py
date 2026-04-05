"""
QuantAgent 策略配置方案数据生成脚本
生成不同风险等级的策略配置方案，覆盖多种策略类型。

数据设计理念：
- 每个策略配置方案代表一种"预设好的策略参数组合"
- 用户可以选择不同的方案进行回测或模拟交易
- 支持的风险等级：保守型、稳健型、平衡型、激进型、超激进型

覆盖策略：
- 三线EMA策略 (ema_triple)
- ATR趋势策略 (atr_trend)
- 海龟策略 (turtle)
- 一目均衡表策略 (ichimoku)

数据范围：2024.09.19 - 2026.03.19
"""

import asyncio
import hashlib
import json
import uuid
import random
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

# 数据库连接
from app.services.database import get_db
from app.models.db_models import (
    BacktestResult, PaperTrade, PaperPosition, PaperAccount,
    EquitySnapshot, PerformanceMetric, TradePair
)

# 设置随机种子以确保可重复性
np.random.seed(42)
random.seed(42)


def compute_params_hash(params: Dict) -> str:
    """Compute SHA256 hash of strategy parameters for matching."""
    return hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()


# ============================================================================
# 策略配置方案定义
# ============================================================================

class StrategyProfile:
    """策略配置方案"""
    def __init__(self, profile_id: str, name: str, description: str, 
                 risk_level: str, initial_capital: float, 
                 max_position_pct: float, strategy_type: str, params: Dict):
        self.profile_id = profile_id
        self.name = name
        self.description = description
        self.risk_level = risk_level
        self.initial_capital = initial_capital
        self.max_position_pct = max_position_pct
        self.strategy_type = strategy_type
        self.params = params

# 定义所有策略配置方案
STRATEGY_PROFILES = [
    # ===== 保守型方案 =====
    StrategyProfile(
        profile_id="conservative_ema_1",
        name="保守型 EMA 趋势策略 (慢速)",
        description="使用较长周期的EMA参数，追求稳定收益，回撤控制严格。适合风险厌恶型投资者。",
        risk_level="conservative",
        initial_capital=100000,
        max_position_pct=0.10,
        strategy_type="ema_triple",
        params={"fast_period": 10, "mid_period": 30, "slow_period": 120}
    ),
    StrategyProfile(
        profile_id="conservative_atr_1",
        name="保守型 ATR 趋势策略 (宽止损)",
        description="使用宽止损倍数，ATR周期较长，减少频繁交易，追求稳健收益。",
        risk_level="conservative",
        initial_capital=100000,
        max_position_pct=0.10,
        strategy_type="atr_trend",
        params={"atr_period": 21, "atr_multiplier": 3.0, "trend_period": 30}
    ),
    StrategyProfile(
        profile_id="conservative_turtle_1",
        name="保守型 海龟策略 (长周期)",
        description="使用长周期唐奇安通道，入场条件严格，减少交易频率。",
        risk_level="conservative",
        initial_capital=100000,
        max_position_pct=0.10,
        strategy_type="turtle",
        params={"entry_period": 55, "exit_period": 20}
    ),
    StrategyProfile(
        profile_id="conservative_ichi_1",
        name="保守型 一目均衡表策略 (长周期)",
        description="使用长周期参数，信号确认严格，减少假信号。",
        risk_level="conservative",
        initial_capital=100000,
        max_position_pct=0.10,
        strategy_type="ichimoku",
        params={"tenkan_period": 12, "kijun_period": 30, "senkou_b_period": 60}
    ),

    # ===== 稳健型方案 =====
    StrategyProfile(
        profile_id="moderate_ema_1",
        name="稳健型 EMA 趋势策略 (标准)",
        description="标准周期的EMA三线策略，平衡收益与风险。",
        risk_level="moderate",
        initial_capital=500000,
        max_position_pct=0.20,
        strategy_type="ema_triple",
        params={"fast_period": 8, "mid_period": 20, "slow_period": 60}
    ),
    StrategyProfile(
        profile_id="moderate_atr_1",
        name="稳健型 ATR 趋势策略 (标准)",
        description="标准ATR参数，中等止损幅度，适合大多数投资者。",
        risk_level="moderate",
        initial_capital=500000,
        max_position_pct=0.20,
        strategy_type="atr_trend",
        params={"atr_period": 14, "atr_multiplier": 2.5, "trend_period": 20}
    ),
    StrategyProfile(
        profile_id="moderate_turtle_1",
        name="稳健型 海龟策略 (标准)",
        description="经典海龟参数，均衡的入场出场周期。",
        risk_level="moderate",
        initial_capital=500000,
        max_position_pct=0.20,
        strategy_type="turtle",
        params={"entry_period": 20, "exit_period": 10}
    ),
    StrategyProfile(
        profile_id="moderate_ichi_1",
        name="稳健型 一目均衡表策略 (标准)",
        description="标准一目均衡表参数，平衡趋势确认与交易频率。",
        risk_level="moderate",
        initial_capital=500000,
        max_position_pct=0.20,
        strategy_type="ichimoku",
        params={"tenkan_period": 9, "kijun_period": 26, "senkou_b_period": 52}
    ),

    # ===== 平衡型方案 =====
    StrategyProfile(
        profile_id="balanced_ema_1",
        name="平衡型 EMA 趋势策略 (快速)",
        description="较快周期的EMA参数，捕捉更多趋势机会，收益潜力更高。",
        risk_level="balanced",
        initial_capital=1000000,
        max_position_pct=0.30,
        strategy_type="ema_triple",
        params={"fast_period": 5, "mid_period": 20, "slow_period": 60}
    ),
    StrategyProfile(
        profile_id="balanced_atr_1",
        name="平衡型 ATR 趋势策略 (紧凑)",
        description="较窄止损幅度，捕捉更多短期趋势。",
        risk_level="balanced",
        initial_capital=1000000,
        max_position_pct=0.30,
        strategy_type="atr_trend",
        params={"atr_period": 14, "atr_multiplier": 2.0, "trend_period": 20}
    ),
    StrategyProfile(
        profile_id="balanced_turtle_1",
        name="平衡型 海龟策略 (快速)",
        description="较短周期捕捉更多交易机会。",
        risk_level="balanced",
        initial_capital=1000000,
        max_position_pct=0.30,
        strategy_type="turtle",
        params={"entry_period": 20, "exit_period": 15}
    ),
    StrategyProfile(
        profile_id="balanced_ichi_1",
        name="平衡型 一目均衡表策略 (快速)",
        description="较短转换线周期，更敏感的趋势信号。",
        risk_level="balanced",
        initial_capital=1000000,
        max_position_pct=0.30,
        strategy_type="ichimoku",
        params={"tenkan_period": 9, "kijun_period": 26, "senkou_b_period": 60}
    ),

    # ===== 激进型方案 =====
    StrategyProfile(
        profile_id="aggressive_ema_1",
        name="激进型 EMA 趋势策略 (高频)",
        description="高频EMA参数，快速响应趋势变化，追求高收益。",
        risk_level="aggressive",
        initial_capital=2000000,
        max_position_pct=0.50,
        strategy_type="ema_triple",
        params={"fast_period": 5, "mid_period": 15, "slow_period": 50}
    ),
    StrategyProfile(
        profile_id="aggressive_atr_1",
        name="激进型 ATR 趋势策略 (紧止损)",
        description="紧止损幅度，快速止损出场，捕捉强势趋势。",
        risk_level="aggressive",
        initial_capital=2000000,
        max_position_pct=0.50,
        strategy_type="atr_trend",
        params={"atr_period": 14, "atr_multiplier": 1.5, "trend_period": 15}
    ),
    StrategyProfile(
        profile_id="aggressive_turtle_1",
        name="激进型 海龟策略 (高频)",
        description="短周期入场，快速捕捉趋势转折。",
        risk_level="aggressive",
        initial_capital=2000000,
        max_position_pct=0.50,
        strategy_type="turtle",
        params={"entry_period": 15, "exit_period": 10}
    ),
    StrategyProfile(
        profile_id="aggressive_ichi_1",
        name="激进型 一目均衡表策略 (灵敏)",
        description="灵敏参数设置，快速响应市场变化。",
        risk_level="aggressive",
        initial_capital=2000000,
        max_position_pct=0.50,
        strategy_type="ichimoku",
        params={"tenkan_period": 9, "kijun_period": 20, "senkou_b_period": 52}
    ),

    # ===== 超激进型方案 =====
    StrategyProfile(
        profile_id="ultra_ema_1",
        name="超激进型 EMA 趋势策略 (超快速)",
        description="超快周期EMA，极高交易频率，追求最大收益。",
        risk_level="ultra_aggressive",
        initial_capital=5000000,
        max_position_pct=0.80,
        strategy_type="ema_triple",
        params={"fast_period": 3, "mid_period": 10, "slow_period": 25}
    ),
    StrategyProfile(
        profile_id="ultra_atr_1",
        name="超激进型 ATR 趋势策略 (极紧密)",
        description="极紧密止损，追逐强势趋势，高风险高回报。",
        risk_level="ultra_aggressive",
        initial_capital=5000000,
        max_position_pct=0.80,
        strategy_type="atr_trend",
        params={"atr_period": 7, "atr_multiplier": 1.5, "trend_period": 10}
    ),
    StrategyProfile(
        profile_id="ultra_turtle_1",
        name="超激进型 海龟策略 (极短周期)",
        description="极短周期捕捉每一个趋势波动，频繁交易。",
        risk_level="ultra_aggressive",
        initial_capital=5000000,
        max_position_pct=0.80,
        strategy_type="turtle",
        params={"entry_period": 10, "exit_period": 5}
    ),
    StrategyProfile(
        profile_id="ultra_ichi_1",
        name="超激进型 一目均衡表策略 (超灵敏)",
        description="超灵敏参数设置，极速响应市场变化。",
        risk_level="ultra_aggressive",
        initial_capital=5000000,
        max_position_pct=0.80,
        strategy_type="ichimoku",
        params={"tenkan_period": 5, "kijun_period": 20, "senkou_b_period": 40}
    ),
]


# 交易对配置
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
INTERVAL = "1d"

# 回测周期
BACKTEST_START = datetime(2024, 9, 19)
BACKTEST_END = datetime(2026, 3, 1)

# 模拟交易周期
PAPER_START = datetime(2026, 3, 1)
PAPER_END = datetime(2026, 3, 19)

# 手续费率
COMMISSION_RATE = 0.0002


# ============================================================================
# 期望收益配置（按风险等级）
# ============================================================================

RISK_EXPECTATIONS = {
    "conservative": {
        "annual_return_range": (5, 15),
        "max_drawdown_range": (3, 10),
        "win_rate_range": (40, 55),
        "profit_factor_range": (1.5, 2.5),
        "trades_per_year_range": (15, 30),
    },
    "moderate": {
        "annual_return_range": (15, 30),
        "max_drawdown_range": (8, 20),
        "win_rate_range": (42, 58),
        "profit_factor_range": (1.3, 2.0),
        "trades_per_year_range": (25, 50),
    },
    "balanced": {
        "annual_return_range": (20, 50),
        "max_drawdown_range": (15, 30),
        "win_rate_range": (40, 55),
        "profit_factor_range": (1.2, 1.8),
        "trades_per_year_range": (35, 70),
    },
    "aggressive": {
        "annual_return_range": (30, 80),
        "max_drawdown_range": (25, 50),
        "win_rate_range": (35, 50),
        "profit_factor_range": (1.0, 1.5),
        "trades_per_year_range": (50, 100),
    },
    "ultra_aggressive": {
        "annual_return_range": (50, 150),
        "max_drawdown_range": (40, 80),
        "win_rate_range": (30, 45),
        "profit_factor_range": (0.8, 1.3),
        "trades_per_year_range": (80, 150),
    },
}


# ============================================================================
# 模拟数据生成器
# ============================================================================

class MockDataGenerator:
    """模拟数据生成器"""

    def __init__(self, symbol: str, profile: StrategyProfile):
        self.symbol = symbol
        self.profile = profile
        self.initial_capital = profile.initial_capital
        self._load_expectations()

    def _load_expectations(self):
        """根据风险等级加载预期收益"""
        exp = RISK_EXPECTATIONS.get(self.profile.risk_level, RISK_EXPECTATIONS["balanced"])
        self.annual_return_range = exp["annual_return_range"]
        self.max_drawdown_range = exp["max_drawdown_range"]
        self.win_rate_range = exp["win_rate_range"]
        self.profit_factor_range = exp["profit_factor_range"]
        self.trades_per_year_range = exp["trades_per_year_range"]

    def generate_backtest_data(self, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """生成回测数据"""
        days = (end_date - start_date).days
        n_days = max(days, 30)

        # 生成交易数量
        min_trades, max_trades = self.trades_per_year_range
        n_trades = int(random.uniform(min_trades, max_trades) * n_days / 365)
        n_trades = max(10, min(80, n_trades))

        # 计算关键指标
        annual_return = random.uniform(*self.annual_return_range)
        max_drawdown = random.uniform(*self.max_drawdown_range)
        win_rate = random.uniform(*self.win_rate_range)
        profit_factor = random.uniform(*self.profit_factor_range)

        # 计算总收益
        total_return = annual_return * (n_days / 365)
        final_capital = self.initial_capital * (1 + total_return / 100)

        # 生成权益曲线
        equity_curve = self._generate_equity_curve(n_days, total_return, max_drawdown)

        # 生成交易记录
        trades = self._generate_trades(n_trades, n_days, win_rate, profit_factor)

        # 计算其他指标
        sharpe_ratio = self._calculate_sharpe(annual_return, max_drawdown)
        total_commission = self.initial_capital * COMMISSION_RATE * n_trades * 2

        metrics = {
            "total_return": round(total_return, 4),
            "annual_return": round(annual_return, 4),
            "max_drawdown": round(max_drawdown, 4),
            "sharpe_ratio": round(sharpe_ratio, 4),
            "win_rate": round(win_rate, 4),
            "profit_factor": round(profit_factor, 4),
            "total_trades": n_trades,
            "total_commission": round(total_commission, 4),
            "initial_capital": self.initial_capital,
            "final_capital": round(final_capital, 4),
            "risk_level": self.profile.risk_level,
            "profile_id": self.profile.profile_id,
        }

        return {
            "params": self.profile.params,
            "metrics": metrics,
            "equity_curve": equity_curve,
            "trades": trades,
        }

    def _generate_equity_curve(self, n_days: int, total_return: float, max_drawdown: float) -> List[Dict]:
        """生成权益曲线"""
        curve = []
        capital = self.initial_capital

        # 生成带趋势和回撤的权益曲线
        trend_slope = total_return / n_days / 100
        daily_vol = max_drawdown / n_days / 100 * random.uniform(0.5, 1.5)

        for i in range(n_days):
            # 趋势 + 随机波动 + 回撤
            daily_return = trend_slope + np.random.normal(0, daily_vol)

            # 偶尔触发回撤
            if random.random() < 0.05:
                daily_return -= abs(np.random.normal(0, daily_vol * 2))

            capital = capital * (1 + daily_return)
            curve.append({
                "t": (BACKTEST_START + timedelta(days=i)).strftime("%Y-%m-%d"),
                "v": round(capital, 2)
            })

        # 确保最终权益正确
        if curve:
            target_final = self.initial_capital * (1 + total_return / 100)
            curve[-1]["v"] = round(target_final, 2)

        # 采样到最多500个点
        if len(curve) > 500:
            step = len(curve) // 500
            curve = curve[::step]

        return curve

    def _generate_trades(self, n_trades: int, n_days: int, win_rate: float, profit_factor: float) -> List[Dict]:
        """生成交易记录"""
        trades = []
        win_count = int(n_trades * win_rate / 100)
        loss_count = n_trades - win_count

        # 分配盈亏金额
        avg_win_pct = random.uniform(2, 8) * (1 + (self.profile.max_position_pct - 0.2) * 2)
        avg_loss_pct = avg_win_pct / profit_factor if profit_factor > 0 else avg_win_pct

        # 生成交易时间点
        trade_days = sorted(random.sample(range(n_days), min(n_trades, n_days)))

        entry_price = 50000  # 假设初始价格
        price_drift = (1 + random.uniform(-0.3, 0.5)) ** (1/n_days)  # 价格趋势

        for i, day_idx in enumerate(trade_days):
            is_win = i < win_count

            # 计算盈亏
            if is_win:
                pnl_pct = avg_win_pct * random.uniform(0.5, 1.5)
                pnl = self.initial_capital * pnl_pct / 100 * random.uniform(0.1, 0.3)
            else:
                pnl_pct = -avg_loss_pct * random.uniform(0.5, 1.5)
                pnl = -self.initial_capital * abs(pnl_pct) / 100 * random.uniform(0.05, 0.2)

            # 价格变动
            price_change = random.uniform(-0.05, 0.08)
            entry_price = entry_price * price_drift
            exit_price = entry_price * (1 + price_change)

            entry_time = BACKTEST_START + timedelta(days=day_idx)
            holding_days = random.randint(1, min(30, n_days - day_idx))
            exit_time = entry_time + timedelta(days=holding_days)

            quantity = self.initial_capital * random.uniform(0.1, self.profile.max_position_pct) / entry_price

            trade = {
                "entry_time": entry_time.strftime("%Y-%m-%d %H:%M:%S"),
                "exit_time": min(exit_time, BACKTEST_END).strftime("%Y-%m-%d %H:%M:%S"),
                "entry_price": round(entry_price, 2),
                "exit_price": round(exit_price, 2),
                "quantity": round(quantity, 8),
                "pnl": round(pnl, 4),
                "pnl_pct": round(pnl_pct, 4),
            }
            trades.append(trade)

            entry_price = exit_price

        return trades

    def _calculate_sharpe(self, annual_return: float, max_drawdown: float) -> float:
        """计算夏普比率（简化版）"""
        risk_free_rate = 2.0  # 年化无风险利率
        volatility = max_drawdown / 2  # 估算波动率
        if volatility == 0:
            return 0
        return (annual_return - risk_free_rate) / volatility

    def generate_paper_trades(self, start_date: datetime, end_date: datetime) -> List[Dict]:
        """生成模拟交易记录"""
        days = (end_date - start_date).days
        if days <= 0:
            return []

        # 生成交易数量（较少）
        n_trades = random.randint(3, 8)

        trades = []
        trade_days = sorted(random.sample(range(days), min(n_trades, days)))

        entry_price = 60000  # 模拟起始价格
        price_drift = 1.001  # 轻微上涨趋势

        for i, day_idx in enumerate(trade_days):
            is_win = random.random() < 0.45
            pnl_pct = random.uniform(1, 5) if is_win else -random.uniform(0.5, 3)

            price_change = pnl_pct / 100
            entry_price = entry_price * price_drift
            exit_price = entry_price * (1 + price_change)

            trade_time = start_date + timedelta(days=day_idx)
            holding_hours = random.randint(4, 48)
            exit_time = trade_time + timedelta(hours=holding_hours)

            quantity = self.initial_capital * random.uniform(0.1, self.profile.max_position_pct) / entry_price
            fee = quantity * entry_price * COMMISSION_RATE
            side = "BUY" if i % 2 == 0 else "SELL"

            trade = {
                "symbol": self.symbol,
                "side": side,
                "order_type": "MARKET",
                "quantity": round(quantity, 8),
                "price": round(entry_price, 2),
                "fee": round(fee, 4),
                "pnl": round(quantity * (exit_price - entry_price) - fee * 2, 4) if side == "SELL" else None,
                "status": "FILLED",
                "created_at": trade_time,
            }
            trades.append(trade)

            entry_price = exit_price

        return trades


# ============================================================================
# 数据写入器
# ============================================================================

class DataWriter:
    """数据库数据写入器"""

    def __init__(self):
        self.db = None

    async def __aenter__(self):
        self.db = get_db()
        self.session = await self.db.__aenter__()
        return self

    async def __aexit__(self, *args):
        await self.db.__aexit__(*args)

    async def write_backtest_result(
        self,
        profile: StrategyProfile,
        symbol: str,
        params: Dict,
        metrics: Dict,
        equity_curve: List,
        trades: List,
        created_at: datetime
    ) -> int:
        """写入回测结果"""
        row = BacktestResult(
            strategy_type=profile.strategy_type,
            symbol=symbol,
            interval=INTERVAL,
            params=params,
            metrics=metrics,
            equity_curve=equity_curve,
            trades_summary=trades[:50],  # 只保存前50笔交易
            created_at=created_at,
            data_source='MOCK',
            params_hash=compute_params_hash(params),
        )
        self.session.add(row)
        await self.session.flush()
        return row.id

    async def write_paper_trade(
        self,
        profile: StrategyProfile,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: float,
        fee: float,
        pnl: Optional[float],
        status: str,
        created_at: datetime,
        mode: str = "paper"
    ) -> int:
        """写入模拟交易记录"""
        row = PaperTrade(
            strategy_id=profile.profile_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            fee=fee,
            pnl=pnl,
            status=status,
            mode=mode,
            created_at=created_at,
            data_source='MOCK',
        )
        self.session.add(row)
        await self.session.flush()
        return row.id

    async def write_trade_pair(
        self,
        symbol: str,
        profile: StrategyProfile,
        entry_trade_id: int,
        exit_trade_id: int,
        entry_time: datetime,
        exit_time: datetime,
        entry_price: float,
        exit_price: float,
        quantity: float,
        pnl: float,
        pnl_pct: float
    ) -> int:
        """写入交易对记录"""
        row = TradePair(
            pair_id=str(uuid.uuid4()),
            symbol=symbol,
            strategy_id=profile.profile_id,
            entry_trade_id=entry_trade_id,
            exit_trade_id=exit_trade_id,
            entry_time=entry_time,
            exit_time=exit_time,
            entry_price=entry_price,
            exit_price=exit_price,
            quantity=quantity,
            side="LONG",
            holding_costs=0,
            status="CLOSED" if exit_trade_id else "OPEN",
            pnl=pnl,
            pnl_pct=pnl_pct,
            data_source='MOCK',
        )
        self.session.add(row)
        await self.session.flush()
        return row.id

    async def write_equity_snapshot(
        self,
        timestamp: datetime,
        total_equity: float,
        cash_balance: float,
        position_value: float,
        daily_pnl: float,
        daily_return: float,
        drawdown: float
    ) -> int:
        """写入权益快照"""
        row = EquitySnapshot(
            timestamp=timestamp,
            total_equity=total_equity,
            cash_balance=cash_balance,
            position_value=position_value,
            daily_pnl=daily_pnl,
            daily_return=daily_return,
            drawdown=drawdown,
            data_source='MOCK',
        )
        self.session.add(row)
        await self.session.flush()
        return row.id

    async def write_performance_metric(
        self,
        profile: StrategyProfile,
        period: str,
        start_date: datetime,
        end_date: datetime,
        initial_equity: float,
        final_equity: float,
        total_return: float,
        total_trades: int,
        winning_trades: int,
        losing_trades: int,
        max_drawdown: float,
        sharpe_ratio: float,
        win_rate: float,
        profit_factor: float,
    ) -> int:
        """写入性能指标"""
        row = PerformanceMetric(
            period=period,
            start_date=start_date,
            end_date=end_date,
            initial_equity=initial_equity,
            final_equity=final_equity,
            total_return=total_return,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            max_drawdown=min(max_drawdown, 9999.99),
            max_drawdown_pct=min(max_drawdown, 9999.99),
            volatility=max_drawdown / 2,
            annualized_return=total_return * (365 / max(1, (end_date - start_date).days)),
            sharpe_ratio=min(max(sharpe_ratio, -999.99), 999.99),
            sortino_ratio=min(max(sharpe_ratio * 1.2, -999.99), 999.99),
            calmar_ratio=total_return / max(max_drawdown, 0.01),
            win_rate=min(max(win_rate, 0), 100),
            profit_factor=min(max(profit_factor, 0), 999.99),
        )
        self.session.add(row)
        await self.session.flush()
        return row.id

    async def commit(self):
        """提交事务"""
        await self.session.commit()


# ============================================================================
# 主数据生成流程
# ============================================================================

async def generate_all_data():
    """生成所有模拟数据"""
    print("=" * 70)
    print("QuantAgent 策略配置方案数据生成器")
    print("=" * 70)

    stats = {
        "profiles_generated": 0,
        "backtest_results": 0,
        "paper_trades": 0,
        "trade_pairs": 0,
        "equity_snapshots": 0,
        "performance_metrics": 0,
    }

    async with DataWriter() as writer:
        for profile in STRATEGY_PROFILES:
            print(f"\n处理策略配置方案: {profile.profile_id}")
            print(f"  名称: {profile.name}")
            print(f"  风险等级: {profile.risk_level}")
            print(f"  初始资金: {profile.initial_capital:,.0f}")
            print(f"  策略类型: {profile.strategy_type}")

            stats["profiles_generated"] += 1

            # 为每个策略配置方案选择一个主要交易对
            # BTCUSDT 作为主要展示
            symbol = "BTCUSDT"

            # 生成回测数据
            generator = MockDataGenerator(symbol=symbol, profile=profile)

            # 回测数据
            backtest_data = generator.generate_backtest_data(BACKTEST_START, BACKTEST_END)

            # 写入回测结果
            bt_id = await writer.write_backtest_result(
                profile=profile,
                symbol=symbol,
                params=backtest_data["params"],
                metrics=backtest_data["metrics"],
                equity_curve=backtest_data["equity_curve"],
                trades=backtest_data["trades"],
                created_at=BACKTEST_END - timedelta(days=random.randint(1, 30)),
            )
            stats["backtest_results"] += 1

            # 生成模拟交易数据
            paper_trades = generator.generate_paper_trades(PAPER_START, PAPER_END)

            entry_trade_ids = []
            for trade in paper_trades:
                trade_id = await writer.write_paper_trade(
                    profile=profile,
                    symbol=trade["symbol"],
                    side=trade["side"],
                    order_type=trade["order_type"],
                    quantity=trade["quantity"],
                    price=trade["price"],
                    fee=trade["fee"],
                    pnl=trade["pnl"],
                    status=trade["status"],
                    created_at=trade["created_at"],
                )

                if trade["side"] == "BUY":
                    entry_trade_ids.append((trade_id, trade["created_at"], trade["price"], trade["quantity"]))
                elif trade["side"] == "SELL" and entry_trade_ids:
                    entry = entry_trade_ids.pop(0)
                    pnl = trade["quantity"] * (trade["price"] - entry[2]) - trade["fee"]
                    pnl_pct = (trade["price"] / entry[2] - 1) * 100

                    await writer.write_trade_pair(
                        symbol=symbol,
                        profile=profile,
                        entry_trade_id=entry[0],
                        exit_trade_id=trade_id,
                        entry_time=entry[1],
                        exit_time=trade["created_at"],
                        entry_price=entry[2],
                        exit_price=trade["price"],
                        quantity=trade["quantity"],
                        pnl=pnl,
                        pnl_pct=pnl_pct,
                    )
                    stats["trade_pairs"] += 1

                stats["paper_trades"] += 1

            # 生成性能指标
            metrics = backtest_data["metrics"]
            trades_list = backtest_data["trades"]
            winning = [t for t in trades_list if t.get("pnl", 0) > 0]
            losing = [t for t in trades_list if t.get("pnl", 0) < 0]

            await writer.write_performance_metric(
                profile=profile,
                period="all_time",
                start_date=BACKTEST_START,
                end_date=BACKTEST_END,
                initial_equity=profile.initial_capital,
                final_equity=metrics["final_capital"],
                total_return=metrics["total_return"],
                total_trades=len(trades_list),
                winning_trades=len(winning),
                losing_trades=len(losing),
                max_drawdown=metrics["max_drawdown"],
                sharpe_ratio=metrics["sharpe_ratio"],
                win_rate=metrics["win_rate"],
                profit_factor=metrics["profit_factor"],
            )
            stats["performance_metrics"] += 1

            # 生成权益快照（每日）
            equity_curve = backtest_data["equity_curve"]
            for i, point in enumerate(equity_curve):
                timestamp = BACKTEST_START + timedelta(days=i)
                equity = point["v"]
                daily_pnl = equity - profile.initial_capital if i == 0 else equity - equity_curve[i-1]["v"]
                daily_return = daily_pnl / equity_curve[i-1]["v"] * 100 if i > 0 else 0
                peak = max([p["v"] for p in equity_curve[:i+1]]) if i > 0 else equity
                drawdown = (peak - equity) / peak * 100 if peak > 0 else 0

                await writer.write_equity_snapshot(
                    timestamp=timestamp,
                    total_equity=equity,
                    cash_balance=equity * random.uniform(0.5, 0.9),
                    position_value=equity * random.uniform(0.1, 0.5),
                    daily_pnl=daily_pnl,
                    daily_return=daily_return,
                    drawdown=drawdown,
                )
                stats["equity_snapshots"] += 1

            print(f"  回测记录ID: {bt_id}")
            print(f"  模拟交易数: {len(paper_trades)}")
            print(f"  收益率: {metrics['total_return']:.2f}%")
            print(f"  最大回撤: {metrics['max_drawdown']:.2f}%")
            print(f"  夏普比率: {metrics['sharpe_ratio']:.2f}")

            # 提交该方案的数据
            await writer.commit()
            print(f"  数据已提交")

    print("\n" + "=" * 70)
    print("数据生成完成!")
    print("=" * 70)
    for key, value in stats.items():
        print(f"  {key}: {value}")
    print("=" * 70)

    return stats


def main():
    """主入口"""
    print("开始生成策略配置方案数据...")
    print(f"回测周期: {BACKTEST_START} - {BACKTEST_END}")
    print(f"模拟交易周期: {PAPER_START} - {PAPER_END}")
    print(f"策略配置方案数量: {len(STRATEGY_PROFILES)}")
    print(f"策略类型: ema_triple, atr_trend, turtle, ichimoku")
    print(f"风险等级: conservative, moderate, balanced, aggressive, ultra_aggressive")
    print()

    # 运行异步生成
    stats = asyncio.run(generate_all_data())

    print("\n数据统计汇总:")
    print("-" * 70)
    print(f"{'风险等级':<25} {'策略数量':<10} {'示例方案'}")
    print("-" * 70)
    
    risk_level_counts = {}
    for profile in STRATEGY_PROFILES:
        risk = profile.risk_level
        risk_level_counts[risk] = risk_level_counts.get(risk, 0) + 1
    
    risk_names = {
        "conservative": "保守型",
        "moderate": "稳健型",
        "balanced": "平衡型",
        "aggressive": "激进型",
        "ultra_aggressive": "超激进型",
    }
    
    for risk, count in risk_level_counts.items():
        example = next(p.profile_id for p in STRATEGY_PROFILES if p.risk_level == risk)
        print(f"{risk_names.get(risk, risk):<25} {count:<10} {example}")
    
    print("-" * 70)
    print("\n所有数据生成完成!")


if __name__ == "__main__":
    main()
