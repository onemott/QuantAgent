"""
Equity Tasks
Scheduled tasks for recording equity curve snapshots and performance metrics.
"""

import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.sql import func

from app.services.database import get_db
from app.models.db_models import EquitySnapshot, PaperAccount, PaperPosition

logger = logging.getLogger(__name__)


async def record_equity_snapshot():
    """
    Record an equity snapshot (called hourly by scheduler).
    Captures: total equity, cash balance, position value, daily P&L, drawdown.
    Implements deduplication: only records once per hour.
    """
    try:
        async with get_db() as session:
            hour_start = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

            existing = await session.execute(
                select(EquitySnapshot)
                .where(EquitySnapshot.timestamp >= hour_start)
                .where(EquitySnapshot.timestamp < hour_start + timedelta(hours=1))
            )
            if existing.scalars().first():
                logger.info(f"Equity snapshot already exists for hour {hour_start}, skipping")
                return

            acc_result = await session.execute(
                select(PaperAccount).where(PaperAccount.id == 1)
            )
            account = acc_result.scalar_one_or_none()
            if not account:
                logger.warning("No paper account found, skipping equity snapshot")
                return

            cash_balance = Decimal(str(account.total_usdt))

            pos_result = await session.execute(
                select(PaperPosition).where(PaperPosition.quantity != 0)
            )
            positions = pos_result.scalars().all()

            position_value = Decimal("0")
            for pos in positions:
                qty = Decimal(str(pos.quantity))
                price = Decimal(str(pos.avg_price))
                try:
                    from app.services.binance_service import binance_service
                    symbol_ccxt = pos.symbol.upper()
                    for quote in ("USDT", "BTC", "ETH"):
                        if symbol_ccxt.endswith(quote):
                            base = symbol_ccxt[: -len(quote)]
                            symbol_ccxt = f"{base}/{quote}"
                            break
                    current_price = await binance_service.get_price(symbol_ccxt)
                    if current_price:
                        price = Decimal(str(current_price))
                except Exception:
                    pass

                position_value += abs(qty) * price

            total_equity = cash_balance + position_value

            prev_result = await session.execute(
                select(EquitySnapshot)
                .order_by(EquitySnapshot.timestamp.desc())
                .limit(1)
            )
            prev_snapshot = prev_result.scalar_one_or_none()

            if prev_snapshot:
                prev_equity = Decimal(str(prev_snapshot.total_equity))
                daily_pnl = total_equity - prev_equity
                daily_return = (
                    (daily_pnl / prev_equity) * 100
                ) if prev_equity > 0 else Decimal("0")
            else:
                daily_pnl = Decimal("0")
                daily_return = Decimal("0")

            peak_result = await session.execute(
                select(func.max(EquitySnapshot.total_equity))
            )
            peak = peak_result.scalar()
            if peak is None:
                peak = total_equity

            peak_val = Decimal(str(peak))
            if peak_val > total_equity:
                drawdown = ((peak_val - total_equity) / peak_val) * 100
            else:
                drawdown = Decimal("0")

            snapshot = EquitySnapshot(
                timestamp=datetime.now(timezone.utc),
                total_equity=total_equity,
                cash_balance=cash_balance,
                position_value=position_value,
                daily_pnl=daily_pnl,
                daily_return=daily_return,
                drawdown=drawdown,
            )
            session.add(snapshot)

            logger.info(
                f"Equity snapshot recorded: equity={float(total_equity):.2f}, "
                f"cash={float(cash_balance):.2f}, pos_value={float(position_value):.2f}, "
                f"daily_pnl={float(daily_pnl):.2f}, drawdown={float(drawdown):.2f}%"
            )

    except Exception as e:
        logger.error(f"Failed to record equity snapshot: {e}")
