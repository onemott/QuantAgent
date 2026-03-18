"""
Performance Service
Calculates complete trading performance metrics: returns, Sharpe, Sortino,
max drawdown, Calmar ratio, win rate, profit factor, etc.
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional
import numpy as np

from sqlalchemy import select, func as sqlfunc

from app.services.database import get_db, redis_get, redis_set
from app.models.db_models import TradePair, EquitySnapshot, PaperTrade

logger = logging.getLogger(__name__)

REDIS_METRICS_KEY = "paper:metrics:{period}"


class PerformanceService:
    RISK_FREE_RATE = 0.03  # 3% annual risk-free rate

    async def calculate_metrics(
        self,
        start_date: datetime,
        end_date: datetime,
        initial_capital: Decimal = Decimal("100000"),
    ) -> Dict:
        """Calculate complete performance metrics for a given time range."""

        # 1. Get equity curve
        equity_curve = await self._get_equity_curve(start_date, end_date)

        # 2. Get closed trade pairs with trades for TCA
        closed_pairs_with_tca = await self._get_closed_pairs_with_tca(start_date, end_date)

        # 3. Calculate returns series
        returns = self._calculate_returns(equity_curve)

        # Determine final equity
        if equity_curve:
            final_equity = float(equity_curve[-1]["total_equity"])
        else:
            final_equity = float(initial_capital)

        init_cap = float(initial_capital)
        total_return = ((final_equity / init_cap) - 1) * 100 if init_cap > 0 else 0

        # Basic metrics
        winning = [p for p in closed_pairs_with_tca if p.get("pnl") and p["pnl"] > 0]
        losing = [p for p in closed_pairs_with_tca if p.get("pnl") and p["pnl"] < 0]

        metrics = {
            "initial_capital": init_cap,
            "final_equity": final_equity,
            "total_return": round(total_return, 2),
            "total_pnl": round(final_equity - init_cap, 2),
            "total_trades": len(closed_pairs_with_tca),
            "winning_trades": len(winning),
            "losing_trades": len(losing),
        }

        # Win rate & profit factor
        if metrics["total_trades"] > 0:
            metrics["win_rate"] = round(
                metrics["winning_trades"] / metrics["total_trades"] * 100, 2
            )
        else:
            metrics["win_rate"] = 0

        total_profit = sum(p["pnl"] for p in winning)
        total_loss = abs(sum(p["pnl"] for p in losing))

        metrics["total_profit"] = round(total_profit, 2)
        metrics["total_loss"] = round(total_loss, 2)

        if total_loss > 0:
            metrics["profit_factor"] = round(float(total_profit / total_loss), 2)
        else:
            # Avoid infinity for JSON compatibility
            metrics["profit_factor"] = 99.99 if total_profit > 0 else 0.0

        metrics["avg_profit"] = round(
            float(total_profit / len(winning)), 2
        ) if winning else 0.0
        metrics["avg_loss"] = round(
            float(total_loss / len(losing)), 2
        ) if losing else 0.0

        # Max drawdown
        max_dd, max_dd_pct = self._calculate_max_drawdown(equity_curve)
        metrics["max_drawdown"] = round(max_dd, 2)
        metrics["max_drawdown_pct"] = round(max_dd_pct, 2)

        # TCA (Transaction Cost Analysis)
        tca_metrics = self._calculate_tca_metrics(closed_pairs_with_tca)
        metrics["tca"] = tca_metrics

        # Volatility
        volatility = self._calculate_volatility(returns)
        metrics["volatility"] = round(float(volatility * 100), 2)

        # Annualized return
        days = max((end_date - start_date).days, 1)
        years = days / 365
        if years > 0 and init_cap > 0:
            annualized = (
                ((final_equity / init_cap) ** (1 / years)) - 1
            ) * 100
        else:
            annualized = 0.0
        metrics["annualized_return"] = round(float(annualized), 2)

        # Sharpe ratio
        if volatility > 0:
            metrics["sharpe_ratio"] = round(
                float((annualized / 100 - self.RISK_FREE_RATE) / volatility), 2
            )
        else:
            metrics["sharpe_ratio"] = 0.0

        # Sortino ratio (downside volatility)
        downside_returns = [r for r in returns if r < 0]
        if downside_returns:
            downside_vol = float(np.std(downside_returns) * np.sqrt(252))
        else:
            downside_vol = 0.0

        if downside_vol > 0:
            metrics["sortino_ratio"] = round(
                float((annualized / 100 - self.RISK_FREE_RATE) / downside_vol), 2
            )
        else:
            metrics["sortino_ratio"] = 0.0

        # Calmar ratio
        if max_dd_pct > 0:
            metrics["calmar_ratio"] = round(float(annualized / max_dd_pct), 2)
        else:
            metrics["calmar_ratio"] = 0.0

        # VaR (Value at Risk)
        metrics["var_95"] = round(float(self.calculate_var(returns, 0.95)), 2)
        metrics["var_99"] = round(float(self.calculate_var(returns, 0.99)), 2)

        # Holding time stats
        holding_hours = [
            p["holding_hours"] for p in closed_pairs_with_tca if p.get("holding_hours")
        ]
        metrics["avg_holding_hours"] = round(
            float(np.mean(holding_hours)), 2
        ) if holding_hours else 0

        # Consecutive wins/losses
        metrics["max_consecutive_wins"] = self._max_consecutive(closed_pairs_with_tca, True)
        metrics["max_consecutive_losses"] = self._max_consecutive(closed_pairs_with_tca, False)

        # Period info
        metrics["start_date"] = start_date.isoformat()
        metrics["end_date"] = end_date.isoformat()
        metrics["days"] = days

        return metrics

    async def _get_closed_pairs_with_tca(self, start: datetime, end: datetime) -> List[Dict]:
        """Fetch closed trade pairs and their corresponding trades for TCA calculation."""
        async with get_db() as session:
            from sqlalchemy import select
            
            closed_pairs = []
            
            stmt = (
                select(TradePair)
                .where(TradePair.status == "CLOSED")
                .where(TradePair.exit_time >= start)
                .where(TradePair.exit_time <= end)
                .order_by(TradePair.exit_time.asc())
            )
            result = await session.execute(stmt)
            pairs_rows = result.scalars().all()
            
            if not pairs_rows:
                return []
            
            for pair_row in pairs_rows:
                entry_trade = None
                exit_trade = None
                
                if pair_row.entry_trade_id:
                    entry_stmt = select(PaperTrade).where(PaperTrade.id == pair_row.entry_trade_id)
                    entry_result = await session.execute(entry_stmt)
                    entry_trade = entry_result.scalar_one_or_none()
                
                if pair_row.exit_trade_id:
                    exit_stmt = select(PaperTrade).where(PaperTrade.id == pair_row.exit_trade_id)
                    exit_result = await session.execute(exit_stmt)
                    exit_trade = exit_result.scalar_one_or_none()
                
                p_dict = {
                    "pair_id": pair_row.pair_id,
                    "symbol": pair_row.symbol,
                    "side": pair_row.side,
                    "pnl": float(pair_row.pnl) if pair_row.pnl else 0,
                    "holding_hours": float(pair_row.holding_hours) if pair_row.holding_hours else 0,
                    "entry_price": float(entry_trade.price) if entry_trade else 0,
                    "entry_benchmark": float(entry_trade.benchmark_price) if entry_trade and entry_trade.benchmark_price else (float(entry_trade.price) if entry_trade else 0),
                    "entry_side": entry_trade.side if entry_trade else None,
                    "exit_price": float(exit_trade.price) if exit_trade else 0,
                    "exit_benchmark": float(exit_trade.benchmark_price) if exit_trade and exit_trade.benchmark_price else (float(exit_trade.price) if exit_trade else 0),
                    "exit_side": exit_trade.side if exit_trade else None,
                }
                closed_pairs.append(p_dict)
            
            return closed_pairs

    def _calculate_tca_metrics(self, pairs: List[Dict]) -> Dict:
        """Calculate Transaction Cost Analysis metrics."""
        if not pairs:
            return {
                "avg_entry_slippage_bps": 0,
                "avg_exit_slippage_bps": 0,
                "total_slippage_cost": 0,
                "execution_quality": "N/A"
            }

        entry_slippages = []
        exit_slippages = []
        total_cost = 0

        for p in pairs:
            # Entry Slippage
            # BUY: (fill - bench) / bench
            # SELL: (bench - fill) / bench
            if p["entry_side"] == "BUY":
                s = (p["entry_price"] - p["entry_benchmark"]) / p["entry_benchmark"] if p["entry_benchmark"] > 0 else 0
            else:
                s = (p["entry_benchmark"] - p["entry_price"]) / p["entry_benchmark"] if p["entry_benchmark"] > 0 else 0
            entry_slippages.append(s)
            total_cost += s * p["entry_benchmark"] # Approximation of dollar cost

            # Exit Slippage
            if p["exit_side"]:
                if p["exit_side"] == "BUY":
                    s = (p["exit_price"] - p["exit_benchmark"]) / p["exit_benchmark"] if p["exit_benchmark"] > 0 else 0
                else:
                    s = (p["exit_benchmark"] - p["exit_price"]) / p["exit_benchmark"] if p["exit_benchmark"] > 0 else 0
                exit_slippages.append(s)
                total_cost += s * p["exit_benchmark"]

        avg_entry = float(np.mean(entry_slippages)) if entry_slippages else 0.0
        avg_exit = float(np.mean(exit_slippages)) if exit_slippages else 0.0

        # BPS (Basis Points)
        metrics = {
            "avg_entry_slippage_bps": round(float(avg_entry * 10000), 2),
            "avg_exit_slippage_bps": round(float(avg_exit * 10000), 2),
            "total_slippage_cost": round(float(total_cost), 2),
        }

        # Quality rating
        total_avg_bps = (metrics["avg_entry_slippage_bps"] + metrics["avg_exit_slippage_bps"]) / 2
        if total_avg_bps < 5:
            metrics["execution_quality"] = "Excellent"
        elif total_avg_bps < 15:
            metrics["execution_quality"] = "Good"
        elif total_avg_bps < 30:
            metrics["execution_quality"] = "Fair"
        else:
            metrics["execution_quality"] = "Poor"

        return metrics

    async def _get_equity_curve(
        self, start: datetime, end: datetime
    ) -> List[Dict]:
        """Fetch equity snapshots within range."""
        async with get_db() as session:
            result = await session.execute(
                select(EquitySnapshot)
                .where(EquitySnapshot.timestamp >= start)
                .where(EquitySnapshot.timestamp <= end)
                .order_by(EquitySnapshot.timestamp.asc())
            )
            snapshots = result.scalars().all()

        return [
            {
                "timestamp": s.timestamp.isoformat() if s.timestamp else None,
                "total_equity": float(s.total_equity),
                "cash_balance": float(s.cash_balance),
                "position_value": float(s.position_value) if s.position_value else 0,
                "daily_pnl": float(s.daily_pnl) if s.daily_pnl else 0,
                "daily_return": float(s.daily_return) if s.daily_return else 0,
                "drawdown": float(s.drawdown) if s.drawdown else 0,
            }
            for s in snapshots
        ]

    def _calculate_returns(self, equity_curve: List[Dict]) -> List[float]:
        """Calculate returns series from equity curve."""
        if len(equity_curve) < 2:
            return []

        returns = []
        for i in range(1, len(equity_curve)):
            prev = equity_curve[i - 1]["total_equity"]
            curr = equity_curve[i]["total_equity"]
            if prev > 0:
                ret = (curr - prev) / prev
                returns.append(ret)
        return returns

    def _calculate_max_drawdown(self, equity_curve: List[Dict]) -> tuple:
        """Calculate maximum drawdown (absolute and percentage)."""
        if not equity_curve:
            return 0.0, 0.0

        peak = equity_curve[0]["total_equity"]
        max_dd = 0.0
        max_dd_pct = 0.0

        for point in equity_curve:
            equity = point["total_equity"]
            if equity > peak:
                peak = equity

            dd = peak - equity
            dd_pct = (dd / peak * 100) if peak > 0 else 0

            if dd > max_dd:
                max_dd = dd
                max_dd_pct = dd_pct

        return max_dd, max_dd_pct

    def _calculate_volatility(self, returns: List[float]) -> float:
        """Calculate annualized volatility."""
        if not returns:
            return 0.0
        return float(np.std(returns) * np.sqrt(252))

    def _max_consecutive(self, pairs: List[Dict], winning: bool) -> int:
        """Calculate max consecutive wins or losses."""
        max_streak = current_streak = 0

        for pair in pairs:
            pnl = pair.get("pnl", 0)
            if pnl is None:
                continue

            is_win = pnl > 0
            if is_win == winning:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 0

        return max_streak

    async def get_attribution(self, start_date: datetime, end_date: datetime) -> List[Dict]:
        """Calculate profit attribution by strategy_id."""
        async with get_db() as session:
            stmt = (
                select(
                    TradePair.strategy_id,
                    sqlfunc.sum(TradePair.pnl).label("total_pnl"),
                    sqlfunc.count(TradePair.id).label("trade_count"),
                    sqlfunc.avg(TradePair.pnl_pct).label("avg_pnl_pct")
                )
                .where(TradePair.status == "CLOSED")
                .where(TradePair.exit_time >= start_date)
                .where(TradePair.exit_time <= end_date)
                .group_by(TradePair.strategy_id)
            )
            result = await session.execute(stmt)
            rows = result.all()
            
            attribution = []
            for row in rows:
                attribution.append({
                    "strategy_id": row.strategy_id or "manual",
                    "total_pnl": float(row.total_pnl) if row.total_pnl else 0,
                    "trade_count": row.trade_count,
                    "avg_pnl_pct": float(row.avg_pnl_pct) if row.avg_pnl_pct else 0
                })
            return attribution

    def calculate_var(self, returns: List[float], confidence_level: float = 0.95) -> float:
        """
        Calculate historical VaR (Value at Risk).
        returns: daily returns series
        confidence_level: e.g., 0.95 for 95% VaR
        """
        if len(returns) < 20:
            return 0.0
        
        sorted_returns = sorted(returns)
        var_index = int((1 - confidence_level) * len(sorted_returns))
        
        if var_index >= len(sorted_returns):
            return 0.0
        
        return -sorted_returns[var_index] * 100

    def calculate_concentration(self, position_values: List[float]) -> float:
        """
        Calculate HHI (Herfindahl-Hirschman Index) for position concentration.
        Returns 0-10000, higher means more concentrated.
        """
        if not position_values or sum(position_values) == 0:
            return 0.0
        
        total = sum(position_values)
        weights = [(v / total) ** 2 for v in position_values if v > 0]
        return sum(weights) * 10000


# Singleton
performance_service = PerformanceService()
