"""
Position Analysis Service
Provides real-time position analytics including unrealized P&L,
holding duration, risk exposure, and portfolio-level metrics.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional

from sqlalchemy import select

from app.services.database import get_db
from app.models.db_models import TradePair, PaperPosition, PaperAccount

logger = logging.getLogger(__name__)


class PositionAnalysisService:
    """
    Provides per-position and portfolio-level analytics.
    """

    async def get_position_analytics(
        self, symbol: str, current_price: float
    ) -> Optional[Dict]:
        """Get detailed analytics for a single position."""
        async with get_db() as session:
            # Get current position
            result = await session.execute(
                select(PaperPosition).where(PaperPosition.symbol == symbol)
            )
            position = result.scalar_one_or_none()

            if not position or float(position.quantity) == 0:
                return None

            # Get trade pairs for this symbol
            pairs_result = await session.execute(
                select(TradePair).where(TradePair.symbol == symbol)
                .order_by(TradePair.created_at.desc())
            )
            pairs = pairs_result.scalars().all()

        closed_pairs = [p for p in pairs if p.status == "CLOSED"]
        open_pairs = [p for p in pairs if p.status == "OPEN"]

        qty = float(position.quantity)
        avg_price = float(position.avg_price)

        # Unrealized P&L
        if qty > 0:  # LONG
            unrealized_pnl = (current_price - avg_price) * qty
            unrealized_pnl_pct = ((current_price / avg_price) - 1) * 100 if avg_price > 0 else 0
        else:  # SHORT
            unrealized_pnl = (avg_price - current_price) * abs(qty)
            unrealized_pnl_pct = ((avg_price / current_price) - 1) * 100 if current_price > 0 else 0

        # Holding time analysis
        if open_pairs:
            entry_times = [p.entry_time for p in open_pairs if p.entry_time]
            if entry_times:
                earliest = min(entry_times)
                now = datetime.now(timezone.utc)
                if earliest.tzinfo is None:
                    from datetime import timezone as tz
                    earliest = earliest.replace(tzinfo=tz.utc)
                holding_seconds = (now - earliest).total_seconds()
                holding_hours = holding_seconds / 3600
            else:
                holding_hours = 0
                earliest = None
        else:
            holding_hours = 0
            earliest = None

        # Position value
        total_value = current_price * abs(qty)

        # Historical trade stats for this symbol
        total_trades = len(closed_pairs)
        winning_trades = sum(
            1 for p in closed_pairs if p.pnl and float(p.pnl) > 0
        )
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

        realized_pnl = sum(
            float(p.pnl) for p in closed_pairs if p.pnl
        )
        avg_pnl = realized_pnl / total_trades if total_trades > 0 else 0

        return {
            "symbol": symbol,
            "side": "LONG" if qty > 0 else "SHORT",
            "quantity": qty,
            "avg_price": round(avg_price, 4),
            "current_price": round(current_price, 4),
            # Unrealized P&L
            "unrealized_pnl": round(unrealized_pnl, 2),
            "unrealized_pnl_pct": round(unrealized_pnl_pct, 2),
            # Holding analysis
            "holding_hours": round(holding_hours, 2),
            "open_position_count": len(open_pairs),
            "entry_time": earliest.isoformat() if earliest else None,
            # Risk exposure
            "position_value": round(total_value, 2),
            "position_value_pct": 0,  # filled at portfolio level
            # Historical stats
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "win_rate": round(win_rate, 2),
            "avg_pnl": round(avg_pnl, 2),
            "realized_pnl": round(realized_pnl, 2),
        }

    async def get_portfolio_analytics(
        self, positions: List[Dict], current_prices: Dict[str, float]
    ) -> Dict:
        """Get portfolio-level analytics across all positions."""

        # Get account balance
        async with get_db() as session:
            result = await session.execute(
                select(PaperAccount).where(PaperAccount.id == 1)
            )
            account = result.scalar_one_or_none()
            cash = float(account.total_usdt) if account else 100000.0

        # Calculate position values
        total_position_value = 0.0
        total_unrealized_pnl = 0.0
        asset_allocation = []
        long_exposure = 0.0
        short_exposure = 0.0

        for pos in positions:
            symbol = pos["symbol"]
            qty = pos["quantity"]
            avg = pos["avg_price"]
            price = current_prices.get(symbol, avg)
            value = abs(qty) * price

            total_position_value += value

            if qty > 0:  # LONG
                pnl = (price - avg) * qty
                long_exposure += value
            else:  # SHORT
                pnl = (avg - price) * abs(qty)
                short_exposure += value

            total_unrealized_pnl += pnl

        total_equity = cash + total_position_value

        # Asset allocation
        for pos in positions:
            symbol = pos["symbol"]
            qty = pos["quantity"]
            avg = pos["avg_price"]
            price = current_prices.get(symbol, avg)
            value = abs(qty) * price
            alloc_pct = (value / total_equity * 100) if total_equity > 0 else 0

            asset_allocation.append({
                "symbol": symbol,
                "value": round(value, 2),
                "allocation_pct": round(alloc_pct, 2),
                "side": "LONG" if qty > 0 else "SHORT",
            })

        # Sort by allocation descending
        asset_allocation.sort(key=lambda x: x["allocation_pct"], reverse=True)

        return {
            "total_equity": round(total_equity, 2),
            "cash": round(cash, 2),
            "position_value": round(total_position_value, 2),
            "cash_pct": round(
                (cash / total_equity * 100) if total_equity > 0 else 100, 2
            ),
            "total_unrealized_pnl": round(total_unrealized_pnl, 2),
            "asset_allocation": asset_allocation,
            "exposure": {
                "long": round(long_exposure, 2),
                "short": round(short_exposure, 2),
                "net_exposure": round(long_exposure - short_exposure, 2),
                "gross_exposure": round(long_exposure + short_exposure, 2),
                "leverage": round(
                    (long_exposure + short_exposure) / total_equity, 2
                ) if total_equity > 0 else 0,
            },
            "position_count": len(positions),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    
    def calculate_concentration_hhi(self, position_values: List[float]) -> float:
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
position_analysis_service = PositionAnalysisService()
