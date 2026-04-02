"""
Paper Trading Service
Handles virtual account management, order execution, and position tracking.
All state is persisted to PostgreSQL; hot data cached in Redis.
Risk pre-checks are delegated to RiskManager before any BUY order is executed.
"""

import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import List, Optional, Dict, Any

from sqlalchemy import select, delete, func as sqlfunc
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.services.database import get_db, redis_get, redis_set, redis_delete
from app.models.db_models import (
    PaperAccount,
    PaperAccountReplay,
    PaperPosition,
    PaperTrade,
    AuditLog,
    EquitySnapshot,
)
from app.services.risk_manager import risk_manager
from app.services.binance_service import binance_service

logger = logging.getLogger(__name__)

# Fee rate: 0.1% per trade (Binance maker/taker)
FEE_RATE = Decimal("0.001")
SLIPPAGE_PCT = Decimal("0.0005")  # 0.05% slippage for market orders
INITIAL_BALANCE = Decimal("100000.0")

# Redis cache keys
REDIS_BALANCE_KEY = "paper:balance"
REDIS_POSITIONS_KEY = "paper:positions"
REDIS_REPLAY_BALANCE_PREFIX = "replay:balance:"  # + session_id


class PaperTradingService:
    """
    Simulated trading engine.
    - Fetches real-time price from BinanceService at order time
    - Persists all trades/positions to PostgreSQL
    - Caches balance + positions in Redis (TTL 10s)
    """

    def __init__(self):
        self.simulated_time: Optional[datetime] = None

    def set_simulated_time(self, timestamp: datetime):
        """Set simulated time for historical replay mode"""
        self.simulated_time = timestamp
        logger.debug(f"PaperTradingService simulated time set to: {timestamp}")

    def _get_current_time(self) -> datetime:
        """Get current time (real or simulated)"""
        return self.simulated_time or datetime.now(timezone.utc)

    # ─────────────────────────────────────────────────────────────
    # Account Balance
    # ─────────────────────────────────────────────────────────────
    async def get_balance(
        self,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Return current USDT balance.

        - With session_id: reads from the session-isolated PaperAccountReplay table.
        - Without session_id: reads from the global PaperAccount(id=1).
        """
        if session_id:
            # Session-isolated balance (replay mode)
            cache_key = f"{REDIS_REPLAY_BALANCE_PREFIX}{session_id}"
            cached = await redis_get(cache_key)
            if cached is not None:
                return cached

            async with get_db() as session:
                result = await session.execute(
                    select(PaperAccountReplay).where(
                        PaperAccountReplay.session_id == session_id
                    )
                )
                account = result.scalar_one_or_none()
                if account is None:
                    return {
                        "total_balance": 0.0,
                        "available_balance": 0.0,
                        "assets": [],
                        "session_id": session_id,
                        "initial_capital": 0.0,
                    }
                balance = float(account.total_usdt)
                data = {
                    "total_balance": balance,
                    "available_balance": balance,
                    "assets": [{"asset": "USDT", "free": balance, "locked": 0.0}],
                    "session_id": session_id,
                    "initial_capital": float(account.initial_capital),
                }
            await redis_set(cache_key, data, ttl=10)
            return data
        else:
            # Global paper trading balance (original logic)
            cached = await redis_get(REDIS_BALANCE_KEY)
            if cached is not None:
                return cached

            async with get_db() as session:
                result = await session.execute(
                    select(PaperAccount).where(PaperAccount.id == 1)
                )
                account = result.scalar_one_or_none()
                if account is None:
                    account = PaperAccount(id=1, total_usdt=INITIAL_BALANCE)
                    session.add(account)
                    await session.commit()
                    await session.refresh(account)

                balance = float(account.total_usdt)

            data = {
                "total_balance": balance,
                "available_balance": balance,
                "assets": [{"asset": "USDT", "free": balance, "locked": 0.0}],
            }
            await redis_set(REDIS_BALANCE_KEY, data, ttl=10)
            return data

    async def _get_usdt_balance(self, session) -> Decimal:
        result = await session.execute(select(PaperAccount).where(PaperAccount.id == 1))
        account = result.scalar_one_or_none()
        if account is None:
            account = PaperAccount(id=1, total_usdt=INITIAL_BALANCE)
            session.add(account)
            await session.flush()
        return Decimal(str(account.total_usdt))

    async def _update_usdt_balance(self, session, new_balance: Decimal):
        result = await session.execute(select(PaperAccount).where(PaperAccount.id == 1))
        account = result.scalar_one_or_none()
        now = self._get_current_time()
        if account is None:
            account = PaperAccount(id=1, total_usdt=new_balance, updated_at=now)
            session.add(account)
        else:
            account.total_usdt = new_balance
            account.updated_at = now
        await redis_delete(REDIS_BALANCE_KEY)

    # ── Session-isolated balance helpers (replay mode) ─────────────────────────
    async def _get_replay_usdt_balance(
        self, session_id: str, session
    ) -> Decimal:
        """Get USDT balance from the session-isolated replay account."""
        result = await session.execute(
            select(PaperAccountReplay).where(
                PaperAccountReplay.session_id == session_id
            )
        )
        account = result.scalar_one_or_none()
        if account is None:
            raise ValueError(f"Replay account not found for session {session_id}")
        return Decimal(str(account.total_usdt))

    async def _update_replay_usdt_balance(
        self, session_id: str, session, new_balance: Decimal
    ):
        """Update balance for the session-isolated replay account."""
        result = await session.execute(
            select(PaperAccountReplay).where(
                PaperAccountReplay.session_id == session_id
            )
        )
        account = result.scalar_one_or_none()
        now = self._get_current_time()
        if account is None:
            raise ValueError(f"Replay account not found for session {session_id}")
        account.total_usdt = new_balance
        account.updated_at = now
        await redis_delete(f"{REDIS_REPLAY_BALANCE_PREFIX}{session_id}")

    # ─────────────────────────────────────────────────────────────
    # Positions
    # ─────────────────────────────────────────────────────────────
    async def get_positions(
        self,
        current_prices: Optional[Dict[str, float]] = None,
        session_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Return open positions with real-time PnL.
        current_prices: {symbol: price} dict for PnL calculation.
        If not provided, will try to fetch from BinanceService.
        """
        # If no session_id, fallback to "paper" mode (global positions)
        async with get_db() as session:
            stmt = select(PaperPosition).where(PaperPosition.quantity != 0)
            if session_id:
                stmt = stmt.where(PaperPosition.session_id == session_id)
            else:
                stmt = stmt.where(PaperPosition.session_id.is_(None))

            result = await session.execute(stmt)
            rows = result.scalars().all()

        # Collect all symbols from positions
        symbols = [row.symbol for row in rows]

        # If no current_prices provided, try to get real-time prices
        prices_to_use = current_prices or {}
        if not current_prices and symbols:
            # Fetch real-time prices from BinanceService
            for sym in set(symbols):
                try:
                    price = await binance_service.get_price(sym)
                    prices_to_use[sym] = price
                except Exception as e:
                    logger.warning(f"Failed to fetch price for {sym}: {e}")
                    # Fallback to avg_price if we can't get real price
                    for row in rows:
                        if row.symbol == sym:
                            prices_to_use[sym] = float(row.avg_price)
                            break

        positions = []
        for row in rows:
            qty = float(row.quantity)
            avg = float(row.avg_price)
            symbol = row.symbol
            mark_price = prices_to_use.get(symbol, avg)

            # PnL Logic:
            # Long (Qty > 0): (Mark - Avg) * Qty
            # Short (Qty < 0): (Avg - Mark) * abs(Qty) = (Avg - Mark) * (-Qty) = (Mark - Avg) * Qty
            # Formula works for both.
            pnl = (mark_price - avg) * qty
            pnl_pct = (
                ((mark_price / avg) - 1) * 100 * (1 if qty > 0 else -1)
                if avg > 0
                else 0.0
            )

            positions.append(
                {
                    "symbol": symbol,
                    "side": "LONG" if qty > 0 else "SHORT",
                    "quantity": qty,
                    "avg_price": avg,
                    "leverage": row.leverage,
                    "liquidation_price": float(row.liquidation_price)
                    if row.liquidation_price
                    else None,
                    "mark_price": mark_price,
                    "pnl": round(pnl, 4),
                    "pnl_pct": round(pnl_pct, 4),
                    "updated_at": row.updated_at.isoformat()
                    if row.updated_at
                    else None,
                }
            )

        # Always update cache (even with fetched prices) for consistency
        await redis_set(REDIS_POSITIONS_KEY, positions, ttl=10)
        return positions

    async def reset_session(self, initial_capital: float, session_id: str) -> None:
        """Reset a replay session to a clean state with its own isolated account."""
        async with get_db() as session:
            # 1. Clear session-scoped trades/positions/snapshots
            await session.execute(
                delete(PaperPosition).where(PaperPosition.session_id == session_id)
            )
            await session.execute(
                delete(PaperTrade).where(PaperTrade.session_id == session_id)
            )
            await session.execute(
                delete(EquitySnapshot).where(EquitySnapshot.session_id == session_id)
            )

            # 2. Create or reset the session's dedicated replay account
            result = await session.execute(
                select(PaperAccountReplay).where(
                    PaperAccountReplay.session_id == session_id
                )
            )
            existing = result.scalar_one_or_none()
            now = self._get_current_time()

            if existing:
                existing.total_usdt = Decimal(str(initial_capital))
                existing.initial_capital = Decimal(str(initial_capital))
                existing.updated_at = now
            else:
                new_account = PaperAccountReplay(
                    session_id=session_id,
                    total_usdt=Decimal(str(initial_capital)),
                    initial_capital=Decimal(str(initial_capital)),
                    created_at=now,
                    updated_at=now,
                )
                session.add(new_account)

            await session.commit()

        # 3. Invalidate caches
        await redis_delete(f"{REDIS_REPLAY_BALANCE_PREFIX}{session_id}")
        await redis_delete(REDIS_POSITIONS_KEY)

    async def _get_position(
        self, session, symbol: str, session_id: Optional[str] = None
    ) -> Optional[PaperPosition]:
        stmt = select(PaperPosition).where(PaperPosition.symbol == symbol)
        if session_id:
            stmt = stmt.where(PaperPosition.session_id == session_id)
        else:
            stmt = stmt.where(PaperPosition.session_id.is_(None))

        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    # ─────────────────────────────────────────────────────────────
    # Order Execution
    # ─────────────────────────────────────────────────────────────
    async def create_order(
        self,
        symbol: str,
        side: str,  # "BUY" | "SELL"
        quantity: float,
        price: float,  # real-time price from BinanceService
        order_type: str = "MARKET",
        benchmark_price: Optional[float] = None,  # For TCA (Implementation Shortfall)
        client_order_id: Optional[str] = None,  # For idempotency
        leverage: int = 1,  # Added leverage parameter
        strategy_id: Optional[str] = None,  # Added for attribution
        mode: str = "paper",  # paper | backtest | historical_replay
        session_id: Optional[str] = None,  # For historical_replay session_id
    ) -> Dict[str, Any]:
        """
        Execute a simulated market order or place a limit order.
        Performs risk pre-check before executing.
        Returns the created trade record dict.
        """
        side = side.upper()
        if side not in ("BUY", "SELL"):
            raise ValueError(f"Invalid side: {side}")
        if quantity <= 0:
            raise ValueError("Quantity must be positive")
        if price <= 0:
            raise ValueError("Price must be positive")

        # Get current time for all records
        now = self._get_current_time()

        # Idempotency check: if client_order_id provided, check for existing trade
        if client_order_id:
            async with get_db() as session:
                from sqlalchemy import select

                existing = await session.execute(
                    select(PaperTrade).where(
                        PaperTrade.client_order_id == client_order_id
                    )
                )
                existing_trade = existing.scalar_one_or_none()
                if existing_trade:
                    logger.info(
                        f"Duplicate order detected, returning existing trade {existing_trade.id} for client_order_id={client_order_id}"
                    )
                    return {
                        "order_id": f"PT-{existing_trade.id}",
                        "symbol": existing_trade.symbol,
                        "side": existing_trade.side,
                        "order_type": existing_trade.order_type,
                        "quantity": float(existing_trade.quantity),
                        "price": float(existing_trade.price),
                        "benchmark_price": float(existing_trade.benchmark_price)
                        if existing_trade.benchmark_price
                        else None,
                        "fee": float(existing_trade.fee),
                        "pnl": float(existing_trade.pnl)
                        if existing_trade.pnl
                        else None,
                        "status": existing_trade.status,
                        "created_at": existing_trade.created_at.isoformat()
                        if existing_trade.created_at
                        else now.isoformat(),
                        "duplicate": True,
                    }

        # Default benchmark to current price if not provided
        if benchmark_price is None:
            benchmark_price = price

        # ── 风控前置检查 ────────────────────────────────────────────────────
        balance_data = await self.get_balance(session_id=session_id)
        available_balance = balance_data.get("available_balance", 0.0)
        positions_data = await self.get_positions(session_id=session_id)
        current_positions = {p["symbol"]: p["quantity"] for p in positions_data}
        total_portfolio = available_balance + sum(
            p["quantity"] * p["mark_price"] for p in positions_data
        )

        risk_result = await risk_manager.check_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            current_balance=available_balance,
            current_positions=current_positions,
            total_portfolio_value=total_portfolio,
            market_price=price,
            leverage=leverage,
        )
        if not risk_result.allowed:
            raise ValueError(f"[风控拦截] {risk_result.reason}")
        # ──────────────────────────────────────────────────────────────────

        qty_dec = Decimal(str(quantity))
        price_dec = Decimal(str(price))
        fee = qty_dec * price_dec * FEE_RATE

        # Handle LIMIT orders (PENDING -> NEW)
        if order_type == "LIMIT":
            async with get_db() as session:
                trade = PaperTrade(
                    client_order_id=client_order_id,
                    strategy_id=strategy_id,
                    symbol=symbol,
                    side=side,
                    order_type="LIMIT",
                    quantity=qty_dec,
                    price=price_dec,
                    benchmark_price=Decimal(str(benchmark_price)),
                    fee=fee,
                    pnl=None,
                    status="NEW",  # Initial state for Limit Order
                    mode=mode,
                    session_id=session_id,
                    created_at=now,
                )
                session.add(trade)
                await session.commit()
                await session.refresh(trade)

                return {
                    "order_id": f"PT-{trade.id}",
                    "symbol": symbol,
                    "side": side,
                    "order_type": "LIMIT",
                    "quantity": float(qty_dec),
                    "price": float(price_dec),
                    "benchmark_price": float(benchmark_price),
                    "fee": float(fee),
                    "pnl": None,
                    "status": "NEW",
                    "created_at": now.isoformat(),
                }

        # MARKET execution (immediate fill)
        async with get_db() as session:
            # Apply Slippage for Market Orders
            # Buy: Execute higher
            # Sell: Execute lower
            slippage_mult = Decimal("1.0")
            if side == "BUY":
                slippage_mult = Decimal("1.0") + SLIPPAGE_PCT
            else:
                slippage_mult = Decimal("1.0") - SLIPPAGE_PCT

            # Adjust execution price
            price_dec = price_dec * slippage_mult

            realized_pnl, new_qty, new_avg = await self._apply_fill_to_account(
                session,
                symbol,
                side,
                qty_dec,
                price_dec,
                fee,
                leverage,
                strategy_id,
                session_id,
            )

            pnl_record = realized_pnl if realized_pnl != 0 else None

            trade = PaperTrade(
                client_order_id=client_order_id,
                strategy_id=strategy_id,
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=qty_dec,
                price=price_dec,
                benchmark_price=Decimal(str(benchmark_price)),
                fee=fee,
                pnl=pnl_record,
                status="FILLED",
                mode=mode,
                session_id=session_id,
                created_at=now,
            )
            session.add(trade)

            # Audit Log
            audit = AuditLog(
                action="ORDER_CREATE",
                user_id="system",
                resource=symbol,
                details={
                    "side": side,
                    "type": order_type,
                    "qty": float(qty_dec),
                    "price": float(price_dec),
                    "benchmark_price": float(benchmark_price),
                    "pnl": float(pnl_record) if pnl_record is not None else None,
                    "new_pos": float(new_qty),
                },
                ip_address="internal",
                created_at=now,
            )
            session.add(audit)

            await session.flush()
            trade_id = trade.id
            created_at = trade.created_at

        # Invalidate caches
        await redis_delete(REDIS_BALANCE_KEY)
        await redis_delete(REDIS_POSITIONS_KEY)

        # Trigger trade pair matching
        try:
            from app.services.trade_pair_service import trade_pair_service

            await trade_pair_service.on_trade_filled(
                trade_id=trade_id,
                symbol=symbol,
                side=side,
                quantity=qty_dec,
                price=price_dec,
                fee=fee,
                created_at=created_at or now,
                strategy_id=strategy_id,
            )
        except Exception as e:
            logger.error(f"Trade pairing failed: {e}")

        # Update Risk Peak Balance
        try:
            new_balance_data = await self.get_balance()
            new_positions_data = await self.get_positions(session_id=session_id)
            total_value = new_balance_data.get("total_balance", 0.0) + sum(
                p["quantity"] * p["mark_price"] for p in new_positions_data
            )
            await risk_manager.update_peak_balance(total_value)
        except Exception as e:
            logger.warning(f"Failed to update peak balance: {e}")

        return {
            "order_id": f"PT-{trade_id}",
            "symbol": symbol,
            "side": side,
            "order_type": order_type,
            "quantity": float(qty_dec),
            "price": float(price_dec),
            "fee": float(fee),
            "pnl": float(pnl_record) if pnl_record is not None else None,
            "status": "FILLED",
            "created_at": created_at.isoformat() if created_at else now.isoformat(),
        }

    async def cancel_order(self, order_id_str: str) -> Dict[str, Any]:
        """Cancel a PENDING order."""
        # order_id_str format: "PT-123"
        try:
            order_id = int(order_id_str.split("-")[1])
        except (IndexError, ValueError):
            raise ValueError(f"Invalid order ID format: {order_id_str}")

        async with get_db() as session:
            result = await session.execute(
                select(PaperTrade).where(PaperTrade.id == order_id)
            )
            order = result.scalar_one_or_none()

            if not order:
                raise ValueError(f"Order {order_id_str} not found")

            if order.status not in ("PENDING", "NEW", "PARTIALLY_FILLED"):
                raise ValueError(
                    f"Order {order_id_str} cannot be canceled (current status: {order.status})"
                )

            order.status = "CANCELED"

            # Audit Log
            audit = AuditLog(
                action="ORDER_CANCEL",
                user_id="system",
                resource=order.symbol,
                details={"order_id": order.id},
                ip_address="internal",
            )
            session.add(audit)
            await session.commit()

        return {"message": f"Order {order_id_str} canceled", "status": "CANCELED"}

    async def _apply_fill_to_account(
        self,
        session,
        symbol: str,
        side: str,
        qty_dec: Decimal,
        price_dec: Decimal,
        fee: Decimal,
        leverage: int = 1,
        strategy_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ):
        """Internal method to update position and balance on trade fill.

        When session_id is provided, uses the session-isolated PaperAccountReplay
        instead of the global PaperAccount(id=1).
        """
        # Choose the correct balance source based on whether this is a replay session
        if session_id:
            usdt_balance = await self._get_replay_usdt_balance(session_id, session)
        else:
            usdt_balance = await self._get_usdt_balance(session)
        position = await self._get_position(session, symbol, session_id)

        # Current Position State
        curr_qty = position.quantity if position else Decimal(0)
        curr_avg = position.avg_price if position else Decimal(0)
        curr_lev = position.leverage if position else 1

        # Determine Delta
        delta_qty = qty_dec if side == "BUY" else -qty_dec

        new_qty = curr_qty + delta_qty
        realized_pnl = Decimal(0)

        # Position Update Logic
        if curr_qty * new_qty >= 0:
            if abs(new_qty) > abs(curr_qty):
                # Opening / Adding
                total_val = (curr_qty * curr_avg) + (delta_qty * price_dec)
                new_avg = total_val / new_qty
                # Use the new leverage for the whole position if it's different
                new_lev = leverage
            else:
                # Closing / Reducing
                new_avg = curr_avg
                new_lev = curr_lev
                realized_pnl = (price_dec - curr_avg) * (-delta_qty)
        else:
            # Flip Position
            realized_pnl = (price_dec - curr_avg) * curr_qty
            new_avg = price_dec
            new_lev = leverage

        # Calculate new liquidation price
        liq_price = None
        if new_qty != 0:
            liq_price_val = risk_manager.calculate_liquidation_price(
                side="BUY" if new_qty > 0 else "SELL",
                entry_price=float(new_avg),
                leverage=new_lev,
            )
            liq_price = Decimal(str(liq_price_val))

        # Update Database (Position)
        now = self._get_current_time()
        if new_qty == 0:
            if position:
                await session.delete(position)
        else:
            if position is None:
                position = PaperPosition(
                    symbol=symbol,
                    session_id=session_id,
                    strategy_id=strategy_id,
                    quantity=new_qty,
                    avg_price=new_avg,
                    leverage=new_lev,
                    liquidation_price=liq_price,
                    updated_at=now,
                )
                session.add(position)
            else:
                position.quantity = new_qty
                position.avg_price = new_avg
                position.leverage = new_lev
                position.liquidation_price = liq_price
                position.updated_at = now
                if strategy_id:
                    position.strategy_id = strategy_id
                if session_id:
                    position.session_id = session_id

        # Update Balance
        # Margin is handled implicitly in paper trading by checking balance in check_order
        # Here we just update the cash balance
        cash_change = -(delta_qty * price_dec) - fee
        new_balance = usdt_balance + cash_change
        if session_id:
            await self._update_replay_usdt_balance(session_id, session, new_balance)
        else:
            await self._update_usdt_balance(session, new_balance)

        return realized_pnl, new_qty, new_avg

    async def match_orders(self):
        """
        Check pending LIMIT orders (NEW/PARTIALLY_FILLED/PENDING) and execute.
        Should be called periodically by scheduler.
        """
        now = self._get_current_time()
        async with get_db() as session:
            # Support multiple active states
            stmt = select(PaperTrade).where(
                PaperTrade.status.in_(["NEW", "PARTIALLY_FILLED", "PENDING"])
            )
            result = await session.execute(stmt)
            pending_orders = result.scalars().all()

            if not pending_orders:
                return

            matched_any = False
            for order in pending_orders:
                try:
                    # Optimized: Check Redis price first via updated BinanceService
                    current_price = await binance_service.get_price(order.symbol)
                except Exception:
                    continue

                matched = False
                limit_price = float(order.price)

                if order.side == "BUY" and current_price <= limit_price:
                    matched = True
                elif order.side == "SELL" and current_price >= limit_price:
                    matched = True

                if matched:
                    # Execute Fill (Full fill for now, Partial logic requires schema update)
                    price_dec = order.price  # Execute at limit price
                    qty_dec = order.quantity
                    fee = order.fee

                    realized_pnl, new_qty, new_avg = await self._apply_fill_to_account(
                        session,
                        order.symbol,
                        order.side,
                        qty_dec,
                        price_dec,
                        fee,
                        strategy_id=order.strategy_id,
                    )

                    pnl_record = realized_pnl if realized_pnl != 0 else None

                    order.status = "FILLED"
                    order.pnl = pnl_record

                    # Audit Log
                    audit = AuditLog(
                        action="ORDER_FILL",
                        user_id="system",
                        resource=order.symbol,
                        details={
                            "order_id": order.id,
                            "side": order.side,
                            "qty": float(qty_dec),
                            "fill_price": float(price_dec),
                            "pnl": float(pnl_record)
                            if pnl_record is not None
                            else None,
                        },
                        created_at=now,
                    )
                    session.add(audit)
                    matched_any = True

                    # Trigger trade pair matching for limit order fill
                    try:
                        from app.services.trade_pair_service import trade_pair_service

                        await trade_pair_service.on_trade_filled(
                            trade_id=order.id,
                            symbol=order.symbol,
                            side=order.side,
                            quantity=qty_dec,
                            price=price_dec,
                            fee=fee,
                            created_at=order.created_at or now,
                            strategy_id=order.strategy_id,
                        )
                    except Exception as e:
                        logger.error(
                            f"Trade pairing failed for limit order {order.id}: {e}"
                        )

            if matched_any:
                await session.commit()
                # Invalidate caches
                await redis_delete(REDIS_BALANCE_KEY)
                await redis_delete(REDIS_POSITIONS_KEY)

    # ─────────────────────────────────────────────────────────────
    # Trade History
    # ─────────────────────────────────────────────────────────────
    async def get_orders(
        self,
        symbol: Optional[str] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Return trade history, optionally filtered by symbol."""
        async with get_db() as session:
            stmt = (
                select(PaperTrade).order_by(PaperTrade.created_at.desc()).limit(limit)
            )
            if symbol:
                stmt = stmt.where(PaperTrade.symbol == symbol)
            result = await session.execute(stmt)
            rows = result.scalars().all()

        orders = []
        for row in rows:
            orders.append(
                {
                    "order_id": f"PT-{row.id}",
                    "symbol": row.symbol,
                    "side": row.side,
                    "order_type": row.order_type,
                    "quantity": float(row.quantity),
                    "price": float(row.price),
                    "fee": float(row.fee),
                    "pnl": float(row.pnl) if row.pnl is not None else None,
                    "status": row.status,
                    "created_at": row.created_at.isoformat()
                    if row.created_at
                    else None,
                }
            )

        return {"orders": orders, "total": len(orders)}

    # ─────────────────────────────────────────────────────────────
    # Limit Order Matching with Historical Bar Prices
    # ─────────────────────────────────────────────────────────────
    async def match_orders_with_bar_price(
        self,
        bar_prices: Dict[str, Dict[str, float]],
        session_id: Optional[str] = None,
    ):
        """
        Match pending LIMIT orders using the current replay bar's OHLC prices.

        This is the core fix for the "limit order uses real-time price" bug.
        When replaying history, limit orders should only fill if their limit price
        was reachable within the bar's [low, high] range — not at the current
        real-time market price.

        Args:
            bar_prices: {symbol: {"high": float, "low": float, "open": float, "close": float}}
            session_id: If provided, limits matching to this replay session's orders
        """
        now = self._get_current_time()
        async with get_db() as session:
            # Only match orders for symbols present in the current bar
            symbols = list(bar_prices.keys())
            if not symbols:
                return

            stmt = select(PaperTrade).where(
                PaperTrade.status.in_(["NEW", "PARTIALLY_FILLED", "PENDING"])
            ).where(PaperTrade.symbol.in_(symbols))

            if session_id:
                stmt = stmt.where(PaperTrade.session_id == session_id)

            result = await session.execute(stmt)
            pending_orders = result.scalars().all()

            if not pending_orders:
                return

            matched_any = False
            for order in pending_orders:
                symbol = order.symbol
                if symbol not in bar_prices:
                    continue

                price_data = bar_prices[symbol]
                bar_high = price_data["high"]
                bar_low = price_data["low"]
                limit_price = float(order.price)

                # Check if limit price is reachable within the bar's range
                # BUY order: fills if bar_low <= limit_price (price dropped to/below limit)
                # SELL order: fills if bar_high >= limit_price (price rose to/above limit)
                matched = False
                exec_price: Optional[Decimal] = None

                if order.side == "BUY" and bar_low <= limit_price:
                    matched = True
                    # Fill at limit price (best case for buyer who set a ceiling)
                    exec_price = Decimal(str(min(limit_price, bar_high)))
                elif order.side == "SELL" and bar_high >= limit_price:
                    matched = True
                    # Fill at limit price (best case for seller who set a floor)
                    exec_price = Decimal(str(max(limit_price, bar_low)))

                if matched and exec_price is not None:
                    qty_dec = order.quantity
                    fee = order.fee or (qty_dec * exec_price * FEE_RATE)

                    realized_pnl, new_qty, new_avg = await self._apply_fill_to_account(
                        session,
                        symbol=order.symbol,
                        side=order.side,
                        qty_dec=qty_dec,
                        price_dec=exec_price,
                        fee=fee,
                        leverage=1,
                        strategy_id=order.strategy_id,
                        session_id=session_id,
                    )

                    pnl_record = realized_pnl if realized_pnl != 0 else None
                    order.status = "FILLED"
                    order.pnl = pnl_record

                    # Audit Log
                    audit = AuditLog(
                        action="ORDER_FILL",
                        user_id="system",
                        resource=symbol,
                        details={
                            "order_id": order.id,
                            "side": order.side,
                            "qty": float(qty_dec),
                            "fill_price": float(exec_price),
                            "source": "bar_price_match",
                            "pnl": float(pnl_record) if pnl_record is not None else None,
                        },
                        created_at=now,
                    )
                    session.add(audit)
                    matched_any = True

                    logger.debug(
                        f"Limit order filled via bar price match: {symbol} "
                        f"{order.side} @ {float(exec_price):.2f} "
                        f"(bar [{bar_low:.2f}, {bar_high:.2f}], limit {limit_price:.2f})"
                    )

            if matched_any:
                await session.commit()
                await redis_delete(f"{REDIS_REPLAY_BALANCE_PREFIX}{session_id}" if session_id else REDIS_BALANCE_KEY)
                await redis_delete(REDIS_POSITIONS_KEY)

    # ─────────────────────────────────────────────────────────────
    # Close All Positions
    # ─────────────────────────────────────────────────────────────
    async def close_all_positions(
        self,
        current_prices: Dict[str, float],
        session_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Close every open position at current market price.

        Args:
            current_prices: {symbol: price} dict
            session_id: If provided, only close positions for this replay session
        """
        positions = await self.get_positions(
            current_prices=current_prices,
            session_id=session_id,
        )
        results = []
        for pos in positions:
            symbol = pos["symbol"]
            qty = pos["quantity"]
            price = current_prices.get(symbol)
            if not price:
                continue

            # Determine side to close
            # If Long (qty>0) -> SELL
            # If Short (qty<0) -> BUY
            side = "SELL" if qty > 0 else "BUY"
            abs_qty = abs(qty)

            try:
                result = await self.create_order(
                    symbol=symbol,
                    side=side,
                    quantity=abs_qty,
                    price=price,
                    session_id=session_id,
                )
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to close position {symbol}: {e}")
                results.append({"symbol": symbol, "error": str(e)})
        return results

    async def check_liquidations(self) -> List[Dict[str, Any]]:
        """
        后台清算检查任务：检查所有持仓是否触及清算价。
        由定时任务调用。
        """
        async with get_db() as session:
            result = await session.execute(
                select(PaperPosition).where(PaperPosition.quantity != 0)
            )
            positions = result.scalars().all()

            if not positions:
                return []

            liquidation_results = []
            for pos in positions:
                symbol = pos.symbol
                qty = float(pos.quantity)
                liq_price = (
                    float(pos.liquidation_price) if pos.liquidation_price else None
                )

                if not liq_price:
                    continue

                try:
                    current_price = await binance_service.get_price(symbol)
                except Exception:
                    continue

                triggered = False
                if qty > 0 and current_price <= liq_price:  # 多头清算
                    triggered = True
                elif qty < 0 and current_price >= liq_price:  # 空头清算
                    triggered = True

                if triggered:
                    logger.warning(
                        f"LIQUIDATION TRIGGERED: {symbol} at {current_price} (Liq: {liq_price})"
                    )
                    # 执行清算平仓
                    side = "SELL" if qty > 0 else "BUY"
                    try:
                        order_res = await self.create_order(
                            symbol=symbol,
                            side=side,
                            quantity=abs(qty),
                            price=current_price,
                            order_type="MARKET",
                        )
                        # 记录清算事件
                        await risk_manager._log_risk_event(
                            symbol,
                            "FORCE_LIQUIDATION",
                            True,
                            {
                                "price": current_price,
                                "liq_price": liq_price,
                                "qty": qty,
                            },
                        )
                        liquidation_results.append(order_res)
                    except Exception as e:
                        logger.error(f"Liquidation execution failed for {symbol}: {e}")

            return liquidation_results

    async def record_replay_equity_snapshot(
        self,
        session_id: str,
        timestamp: datetime,
        current_prices: Optional[Dict[str, float]] = None,
    ) -> bool:
        """
        Record an equity snapshot for historical replay with simulated timestamp.
        Uses the session-isolated PaperAccountReplay for cash_balance.

        Args:
            session_id: The replay session ID
            timestamp: The simulated timestamp to record
            current_prices: Dict of {symbol: price} from replay bars

        Returns:
            True if snapshot was recorded, False otherwise
        """
        try:
            async with get_db() as session:
                existing = await session.execute(
                    select(EquitySnapshot)
                    .where(EquitySnapshot.session_id == session_id)
                    .where(
                        EquitySnapshot.timestamp
                        >= timestamp.replace(minute=0, second=0, microsecond=0)
                    )
                    .where(
                        EquitySnapshot.timestamp
                        < timestamp.replace(minute=0, second=0, microsecond=0)
                        + timedelta(hours=1)
                    )
                )
                if existing.scalars().first():
                    return False

                # Read cash balance from session-isolated account (NOT PaperAccount.id=1)
                acc_result = await session.execute(
                    select(PaperAccountReplay).where(
                        PaperAccountReplay.session_id == session_id
                    )
                )
                account = acc_result.scalar_one_or_none()
                if not account:
                    logger.warning(f"Replay account not found for {session_id}")
                    return False

                cash_balance = Decimal(str(account.total_usdt))
                snapshot_initial = Decimal(str(account.initial_capital))

                pos_result = await session.execute(
                    select(PaperPosition).where(
                        PaperPosition.session_id == session_id,
                        PaperPosition.quantity != 0,
                    )
                )
                positions = pos_result.scalars().all()

                position_value = Decimal("0")
                for pos in positions:
                    qty = Decimal(str(pos.quantity))
                    avg = Decimal(str(pos.avg_price))
                    symbol = pos.symbol

                    if current_prices and symbol in current_prices:
                        price = Decimal(str(current_prices[symbol]))
                    else:
                        price = avg

                    position_value += abs(qty) * price

                total_equity = cash_balance + position_value

                prev_result = await session.execute(
                    select(EquitySnapshot)
                    .where(EquitySnapshot.session_id == session_id)
                    .order_by(EquitySnapshot.timestamp.desc())
                    .limit(1)
                )
                prev_snapshot = prev_result.scalar_one_or_none()

                if prev_snapshot:
                    prev_equity = Decimal(str(prev_snapshot.total_equity))
                    daily_pnl = total_equity - prev_equity
                    daily_return = (
                        ((daily_pnl / prev_equity) * 100)
                        if prev_equity > 0
                        else Decimal("0")
                    )
                else:
                    daily_pnl = Decimal("0")
                    daily_return = Decimal("0")

                peak_result = await session.execute(
                    select(sqlfunc.max(EquitySnapshot.total_equity)).where(
                        EquitySnapshot.session_id == session_id
                    )
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
                    timestamp=timestamp,
                    session_id=session_id,
                    total_equity=total_equity,
                    cash_balance=cash_balance,
                    position_value=position_value,
                    daily_pnl=daily_pnl,
                    daily_return=daily_return,
                    drawdown=drawdown,
                    initial_capital=snapshot_initial,
                    data_source='REPLAY',
                )
                session.add(snapshot)
                await session.commit()

                logger.debug(
                    f"Replay equity snapshot recorded: session={session_id}, "
                    f"time={timestamp}, equity={float(total_equity):.2f}"
                )
                return True

        except Exception as e:
            logger.error(f"Failed to record replay equity snapshot: {e}")
            return False


# Singleton instance
paper_trading_service = PaperTradingService()
