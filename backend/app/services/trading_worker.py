import asyncio
import json
import logging
import nats
from nats.errors import ConnectionClosedError, TimeoutError, NoServersError
from typing import Dict, Any

from app.core.config import settings
from app.services.paper_trading_service import paper_trading_service
from app.services.database import get_db
from app.models.db_models import AuditLog

logger = logging.getLogger(__name__)

class TradingWorker:
    """
    Python NATS Trading Worker
    Subscribes to 'trade.signal' and executes trades asynchronously.
    Flow: Signal -> Risk Check (inside paper_trading_service) -> Order Execution -> Audit Log
    """
    def __init__(self):
        self.nc = None
        self.running = False
        self.subscription = None

    async def start(self):
        """Start the NATS trading worker."""
        if self.running:
            return
            
        self.running = True
        try:
            logger.info(f"TradingWorker connecting to NATS: {settings.NATS_URL} ...")
            self.nc = await nats.connect(
                settings.NATS_URL,
                name="quantagent-trading-worker",
                reconnect_time_wait=2,
                max_reconnect_attempts=-1,
                connect_timeout=5
            )
            logger.info("TradingWorker NATS connected.")

            # Subscribe to signals
            # Expected payload: {"symbol": "BTCUSDT", "side": "BUY", "quantity": 0.1, "price": 60000, "client_order_id": "..."}
            self.subscription = await self.nc.subscribe("trade.signal", cb=self._handle_signal)
            logger.info("TradingWorker subscribed to 'trade.signal'")

        except Exception as e:
            logger.error(f"TradingWorker failed to start: {e}")
            self.running = False

    async def stop(self):
        """Stop the worker."""
        self.running = False
        if self.nc:
            try:
                await self.nc.close()
            except Exception:
                pass
            logger.info("TradingWorker NATS connection closed.")

    async def _handle_signal(self, msg):
        """Process incoming trade signal."""
        try:
            data = json.loads(msg.data.decode())
            symbol = data.get("symbol")
            side = data.get("side")
            quantity = data.get("quantity")
            price = data.get("price")
            order_type = data.get("order_type", "MARKET")
            client_order_id = data.get("client_order_id")
            strategy_id = data.get("strategy_id") # Extract strategy_id from signal

            if not all([symbol, side, quantity, price]):
                logger.warning(f"Invalid signal payload: {data}")
                return

            logger.info(f"Received trade signal: {side} {quantity} {symbol} @ {price}")

            # Execute trade via paper_trading_service
            # Note: paper_trading_service.create_order already performs risk checks.
            try:
                result = await paper_trading_service.create_order(
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    price=price,
                    order_type=order_type,
                    client_order_id=client_order_id,
                    strategy_id=strategy_id # Pass strategy_id
                )
                logger.info(f"Trade executed successfully: {result['order_id']}")

                # Log success to AuditLog
                await self._log_audit("SIGNAL_EXECUTION_SUCCESS", symbol, {
                    "signal": data,
                    "result": result
                })

            except ValueError as ve:
                # Risk check failed or invalid params
                logger.warning(f"Trade signal rejected: {ve}")
                await self._log_audit("SIGNAL_EXECUTION_REJECTED", symbol, {
                    "signal": data,
                    "reason": str(ve)
                })
            except Exception as e:
                logger.error(f"Error executing trade signal: {e}")
                await self._log_audit("SIGNAL_EXECUTION_ERROR", symbol, {
                    "signal": data,
                    "error": str(e)
                })

        except Exception as e:
            logger.error(f"Error handling signal message: {e}")

    async def _log_audit(self, action: str, resource: str, details: Dict[str, Any]):
        """Helper to log actions to AuditLog."""
        try:
            async with get_db() as session:
                audit = AuditLog(
                    action=action,
                    user_id="system",
                    resource=resource,
                    details=details
                )
                session.add(audit)
                await session.commit()
        except Exception as e:
            logger.warning(f"Failed to log audit event {action}: {e}")

# Singleton instance
trading_worker = TradingWorker()
