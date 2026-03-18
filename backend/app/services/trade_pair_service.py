"""
Trade Pair Service
Manages order pairing (entry/exit linking) for complete trade lifecycle tracking.
Uses FIFO matching: first open position is paired with first closing trade.
"""

import logging
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, List, Any

from sqlalchemy import select, update
from sqlalchemy.sql import func

from app.services.database import get_db
from app.models.db_models import TradePair, PaperTrade

logger = logging.getLogger(__name__)


class TradePairService:
    """
    Pairs entry and exit trades for P&L tracking.
    - LONG: BUY opens → SELL closes
    - SHORT: SELL opens → BUY closes
    - FIFO: first-in-first-out pairing
    """

    async def on_trade_filled(self, trade_id: int, symbol: str, side: str,
                               quantity: Decimal, price: Decimal, fee: Decimal,
                               created_at: datetime, strategy_id: Optional[str] = None) -> Optional[Dict]:
        """
        Called after a trade is filled. Automatically pairs entry/exit.
        Returns the created or updated TradePair dict, or None.
        """
        try:
            async with get_db() as session:
                # Find existing OPEN pair for this symbol
                existing_pair = await self._find_open_pair(session, symbol)

                if side == "BUY":
                    if existing_pair and existing_pair.side == "SHORT":
                        # Closing a short position
                        return await self._close_pair(session, existing_pair, trade_id,
                                                       price, fee, created_at, quantity)
                    else:
                        # Opening a long position
                        return await self._create_pair(session, trade_id, symbol, "LONG",
                                                        price, fee, created_at, quantity, strategy_id)
                else:  # SELL
                    if existing_pair and existing_pair.side == "LONG":
                        # Closing a long position
                        return await self._close_pair(session, existing_pair, trade_id,
                                                       price, fee, created_at, quantity)
                    else:
                        # Opening a short position
                        return await self._create_pair(session, trade_id, symbol, "SHORT",
                                                        price, fee, created_at, quantity, strategy_id)
        except Exception as e:
            logger.error(f"Trade pairing failed for trade {trade_id}: {e}")
            return None

    async def _find_open_pair(self, session, symbol: str) -> Optional[TradePair]:
        """Find the oldest OPEN pair for a symbol (FIFO)."""
        result = await session.execute(
            select(TradePair)
            .where(TradePair.symbol == symbol)
            .where(TradePair.status == "OPEN")
            .order_by(TradePair.created_at.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _create_pair(self, session, trade_id: int, symbol: str, side: str,
                            price: Decimal, fee: Decimal, created_at: datetime,
                            quantity: Decimal, strategy_id: Optional[str] = None) -> Dict:
        """Create a new trade pair (opening position)."""
        pair = TradePair(
            pair_id=str(uuid.uuid4()),
            symbol=symbol,
            strategy_id=strategy_id,
            entry_trade_id=trade_id,
            entry_time=created_at,
            entry_price=price,
            quantity=quantity,
            side=side,
            status="OPEN",
            holding_costs=fee,
        )
        session.add(pair)
        await session.flush()

        logger.info(f"Created trade pair {pair.pair_id}: {side} {symbol} @ {price}")
        return self._pair_to_dict(pair)

    async def _close_pair(self, session, pair: TradePair, exit_trade_id: int,
                           exit_price: Decimal, exit_fee: Decimal,
                           exit_time: datetime, exit_quantity: Decimal) -> Dict:
        """Close an existing trade pair (closing position)."""
        pair.exit_trade_id = exit_trade_id
        pair.exit_time = exit_time
        pair.exit_price = exit_price
        pair.status = "CLOSED"

        # Accumulate fees
        current_costs = Decimal(str(pair.holding_costs)) if pair.holding_costs else Decimal(0)
        pair.holding_costs = current_costs + exit_fee

        entry_price = Decimal(str(pair.entry_price))
        qty = Decimal(str(pair.quantity))
        costs = Decimal(str(pair.holding_costs))

        # Calculate P&L
        if pair.side == "LONG":
            pnl = (exit_price - entry_price) * qty - costs
            pnl_pct = ((exit_price / entry_price) - 1) * 100 if entry_price > 0 else Decimal(0)
        else:  # SHORT
            pnl = (entry_price - exit_price) * qty - costs
            pnl_pct = ((entry_price / exit_price) - 1) * 100 if exit_price > 0 else Decimal(0)

        pair.pnl = pnl
        pair.pnl_pct = pnl_pct

        # Calculate holding duration
        delta = exit_time - pair.entry_time
        pair.holding_hours = Decimal(str(round(delta.total_seconds() / 3600, 2)))

        await session.flush()

        logger.info(f"Closed trade pair {pair.pair_id}: {pair.side} {pair.symbol} "
                     f"PnL={float(pnl):.2f} ({float(pnl_pct):.2f}%)")
        return self._pair_to_dict(pair)

    async def get_trade_pairs(self, status: Optional[str] = None,
                               symbol: Optional[str] = None,
                               limit: int = 50) -> List[Dict]:
        """Get trade pairs with optional filtering."""
        async with get_db() as session:
            stmt = select(TradePair).order_by(TradePair.created_at.desc()).limit(limit)
            if status:
                stmt = stmt.where(TradePair.status == status)
            if symbol:
                stmt = stmt.where(TradePair.symbol == symbol)

            result = await session.execute(stmt)
            pairs = result.scalars().all()

        return [self._pair_to_dict(p) for p in pairs]

    async def get_pair_detail(self, pair_id: str) -> Optional[Dict]:
        """Get detailed info for a single trade pair including linked trades."""
        async with get_db() as session:
            result = await session.execute(
                select(TradePair).where(TradePair.pair_id == pair_id)
            )
            pair = result.scalar_one_or_none()
            if not pair:
                return None

            # Fetch entry trade
            entry_result = await session.execute(
                select(PaperTrade).where(PaperTrade.id == pair.entry_trade_id)
            )
            entry_trade = entry_result.scalar_one_or_none()

            # Fetch exit trade if exists
            exit_trade = None
            if pair.exit_trade_id:
                exit_result = await session.execute(
                    select(PaperTrade).where(PaperTrade.id == pair.exit_trade_id)
                )
                exit_trade = exit_result.scalar_one_or_none()

        detail = self._pair_to_dict(pair)
        detail["entry"] = {
            "trade_id": entry_trade.id,
            "time": entry_trade.created_at.isoformat() if entry_trade and entry_trade.created_at else None,
            "price": float(entry_trade.price) if entry_trade else None,
            "quantity": float(entry_trade.quantity) if entry_trade else None,
            "fee": float(entry_trade.fee) if entry_trade else None,
        } if entry_trade else None

        detail["exit"] = {
            "trade_id": exit_trade.id,
            "time": exit_trade.created_at.isoformat() if exit_trade.created_at else None,
            "price": float(exit_trade.price),
            "quantity": float(exit_trade.quantity),
            "fee": float(exit_trade.fee),
        } if exit_trade else None

        return detail

    async def get_closed_pairs_in_range(self, start: datetime, end: datetime) -> List[TradePair]:
        """Get all closed pairs within a time range (for performance calculation)."""
        async with get_db() as session:
            result = await session.execute(
                select(TradePair)
                .where(TradePair.status == "CLOSED")
                .where(TradePair.exit_time >= start)
                .where(TradePair.exit_time <= end)
                .order_by(TradePair.exit_time.asc())
            )
            return result.scalars().all()

    def _pair_to_dict(self, pair: TradePair) -> Dict:
        """Convert TradePair ORM object to dict."""
        return {
            "pair_id": pair.pair_id,
            "symbol": pair.symbol,
            "strategy_id": pair.strategy_id,
            "side": pair.side,
            "status": pair.status,
            "entry_trade_id": pair.entry_trade_id,
            "exit_trade_id": pair.exit_trade_id,
            "entry_time": pair.entry_time.isoformat() if pair.entry_time else None,
            "exit_time": pair.exit_time.isoformat() if pair.exit_time else None,
            "entry_price": float(pair.entry_price) if pair.entry_price else None,
            "exit_price": float(pair.exit_price) if pair.exit_price else None,
            "quantity": float(pair.quantity) if pair.quantity else None,
            "holding_costs": float(pair.holding_costs) if pair.holding_costs else 0,
            "pnl": float(pair.pnl) if pair.pnl else None,
            "pnl_pct": float(pair.pnl_pct) if pair.pnl_pct else None,
            "holding_hours": float(pair.holding_hours) if pair.holding_hours else None,
            "created_at": pair.created_at.isoformat() if pair.created_at else None,
        }


# Singleton
trade_pair_service = TradePairService()
