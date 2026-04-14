"""
Strategy Runner Service
Executes quantitative strategies periodically and generates trading signals.
Signals are published to NATS 'trade.signal' for execution by TradingWorker.
Uses DynamicSelectionStrategy in a memory sandbox mode for live paper trading.
"""

import asyncio
import json
import logging
import nats
import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

from app.core.config import settings
from app.services.binance_service import binance_service
from app.services.paper_trading_service import paper_trading_service
from app.models.trading import OrderRequest, OrderResult, TradeSide, BarData
from app.core.bus import TradingBus
from app.strategies.dynamic_selection_strategy import DynamicSelectionStrategy

logger = logging.getLogger(__name__)

# NATS topic for order signals (must match Go gateway subscription)
NATS_ORDER_SIGNAL_TOPIC = "signal.order"

# Active strategy configuration using DynamicSelectionStrategy
DYNAMIC_SELECTION_CONFIG = {
    "strategy_id": "dynamic_weighted",
    "strategy_type": "dynamic_selection",
    "symbol": "BTCUSDT",
    "interval": "1h",
    "quantity": 0.01,
    "params": {
        "initial_capital": 10000.0,
        "evaluation_period": 1440,
        "weight_method": "score_based",
        "atomic_strategies": [
            {
                "strategy_id": "auto_trend_ma",
                "strategy_type": "ma",
                "params": {"fast_period": 10, "slow_period": 30}
            },
            {
                "strategy_id": "auto_reversion_rsi",
                "strategy_type": "rsi",
                "params": {"rsi_period": 14, "oversold": 30, "overbought": 70}
            },
            {
                "strategy_id": "auto_volatility_boll",
                "strategy_type": "boll",
                "params": {"period": 20, "std_dev": 2.0}
            }
        ]
    }
}

class NATSTradingBus(TradingBus):
    """A proxy bus that publishes orders to NATS instead of real execution."""
    def __init__(self, nc, session_id: str, symbol: str, quantity: float):
        self.nc = nc
        self.session_id = session_id
        self.symbol = symbol
        self.quantity = quantity

    def get_mode(self) -> str:
        return "PAPER"

    def subscribe_bars(self, callback):
        pass

    def subscribe_ticks(self, callback):
        pass

    async def publish_bar(self, bar):
        pass

    async def publish_tick(self, tick):
        pass

    async def jump_to(self, timestamp):
        pass

    def pause(self):
        pass

    def resume(self):
        pass

    def stop(self):
        pass

    async def get_balance(self) -> Dict[str, Any]:
        # Provide enough virtual capital so DynamicSelectionStrategy can emit signals
        return {
            "total_balance": 100000.0,
            "available_balance": 100000.0,
            "total_equity": 100000.0,
            "assets": [{"asset": "USDT", "free": 100000.0, "locked": 0.0}]
        }

    async def execute_order(self, order_req: OrderRequest) -> OrderResult:
        side = "BUY" if order_req.side == TradeSide.BUY else "SELL"
        # Use order_req.quantity if provided and positive, otherwise fall back to self.quantity
        actual_quantity = order_req.quantity if order_req.quantity and order_req.quantity > 0 else self.quantity
        payload = {
            "symbol": self.symbol,
            "side": side,
            "quantity": actual_quantity,
            "source": order_req.strategy_id,
            "price": order_req.price
        }

        if self.nc:
            try:
                await self.nc.publish(NATS_ORDER_SIGNAL_TOPIC, json.dumps(payload).encode())
                logger.info(f"Published composite {side} signal for {self.symbol} @ {order_req.price}")
            except Exception as e:
                logger.error(f"Failed to publish order signal to NATS: {e}")
                return OrderResult(
                    order_id="nats_mock_id",
                    client_order_id=order_req.client_order_id,
                    symbol=self.symbol,
                    status="REJECTED",
                    filled_quantity=0.0,
                    filled_price=order_req.price if order_req.price else 0.0,
                    fee=0.0,
                    pnl=0.0,
                    timestamp=datetime.now(timezone.utc),
                    error_msg=str(e)
                )

        return OrderResult(
            order_id="nats_mock_id",
            client_order_id=order_req.client_order_id,
            symbol=self.symbol,
            status="FILLED",
            filled_quantity=actual_quantity,
            filled_price=order_req.price,
            fee=0.0,
            pnl=0.0,
            timestamp=datetime.now(timezone.utc)
        )

class StrategyRunnerService:
    def __init__(self):
        self.nc = None
        self.strategy: Optional[DynamicSelectionStrategy] = None
        self.is_warmed_up = False
        self.last_bar_time: Optional[datetime] = None

    async def _connect_nats(self):
        if self.nc and self.nc.is_connected:
            return
        try:
            self.nc = await nats.connect(settings.NATS_URL)
            logger.info("StrategyRunner connected to NATS")
            
            # If we reconnected, update the bus nc reference if it exists
            if self.strategy and hasattr(self.strategy, 'bus') and hasattr(self.strategy.bus, 'nc'):
                self.strategy.bus.nc = self.nc
                
        except Exception as e:
            logger.error(f"Failed to connect to NATS: {e}")

    async def _warmup_strategy(self) -> bool:
        """Fetch historical data to warm up the memory sandbox."""
        logger.info("Warming up DynamicSelectionStrategy...")
        
        symbol = DYNAMIC_SELECTION_CONFIG["symbol"]
        interval = DYNAMIC_SELECTION_CONFIG["interval"]
        params = DYNAMIC_SELECTION_CONFIG["params"]
        
        # Need enough data for at least one evaluation cycle + indicators buffer
        # e.g., evaluation_period=1440. Let's fetch 1500 bars
        df = await binance_service.get_klines_dataframe(symbol, interval, limit=1500)
        
        if df is None or df.empty:
            logger.error("Failed to fetch historical data for warmup.")
            return False
            
        bus = NATSTradingBus(
            nc=self.nc, 
            session_id="live_paper_session", 
            symbol=symbol, 
            quantity=DYNAMIC_SELECTION_CONFIG["quantity"]
        )
        
        self.strategy = DynamicSelectionStrategy(
            strategy_id=DYNAMIC_SELECTION_CONFIG["strategy_id"], 
            bus=bus
        )
        self.strategy.set_parameters(params)
        
        # Process historical bars sequentially
        original_nc = bus.nc
        bus.nc = None  # Suppress NATS publish during warmup
        
        for idx, row in df.iterrows():
            bar_time = idx.to_pydatetime()
            if bar_time.tzinfo is None:
                bar_time = bar_time.replace(tzinfo=timezone.utc)
                
            bar = BarData(
                symbol=symbol,
                datetime=bar_time,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"])
            )
            
            await self.strategy.on_bar(bar)
            self.last_bar_time = bar_time
            
        bus.nc = original_nc # Restore NATS connection

        # Restore position from paper trading service
        try:
            symbol = DYNAMIC_SELECTION_CONFIG["symbol"]
            positions = await paper_trading_service.get_positions(session_id="live_paper_session")
            if positions:
                for pos in positions:
                    if pos.get("symbol") == symbol and pos.get("quantity", 0) > 0:
                        self.strategy.current_position = float(pos["quantity"])
                        logger.info(f"Restored position from paper trading: {symbol} qty={self.strategy.current_position}")
                        break
            if self.strategy.current_position == 0:
                logger.info("No existing position found in paper trading service.")
        except Exception as e:
            logger.warning(f"Failed to restore position from paper trading service: {e}. Starting with zero position.")
            self.strategy.current_position = 0.0

        self.is_warmed_up = True
        logger.info(f"Warmup complete. Processed {len(df)} historical bars up to {self.last_bar_time}.")
        return True

    async def run_all_strategies(self):
        """Execute the dynamic selection strategy."""
        await self._connect_nats()
        
        if not self.is_warmed_up:
            success = await self._warmup_strategy()
            if not success:
                return

        symbol = DYNAMIC_SELECTION_CONFIG["symbol"]
        interval = DYNAMIC_SELECTION_CONFIG["interval"]
        
        # Fetch the latest bars (limit=2 is usually enough to get the newest complete/partial bar)
        df = await binance_service.get_klines_dataframe(symbol, interval, limit=2)
        if df is None or df.empty:
            logger.warning(f"Failed to fetch latest data for {symbol}.")
            return
            
        # Get the very latest bar
        latest_row = df.iloc[-1]
        current_bar_time = df.index[-1].to_pydatetime()
        if current_bar_time.tzinfo is None:
            current_bar_time = current_bar_time.replace(tzinfo=timezone.utc)
        
        # Only process if it's a new bar or we want to update the current partial bar
        # For typical bar-based strategies, feeding the same bar multiple times updates the state
        # But we must ensure the datetime advances or is the same (partial bar update)
        if self.last_bar_time is None or current_bar_time > self.last_bar_time:
            bar = BarData(
                symbol=symbol,
                datetime=current_bar_time,
                open=float(latest_row["open"]),
                high=float(latest_row["high"]),
                low=float(latest_row["low"]),
                close=float(latest_row["close"]),
                volume=float(latest_row["volume"])
            )
            
            # Execute on_bar. If a signal is generated, NATSTradingBus will publish it.
            await self.strategy.on_bar(bar)
            
            self.last_bar_time = current_bar_time
            logger.debug(f"Processed new bar at {current_bar_time} for {symbol}")

strategy_runner_service = StrategyRunnerService()
