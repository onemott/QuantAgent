"""
Strategy Runner Service
Executes quantitative strategies periodically and generates trading signals.
Signals are published to NATS 'trade.signal' for execution by TradingWorker.
"""

import asyncio
import json
import logging
import nats
from datetime import datetime, timezone
from typing import List, Dict, Any

from app.core.config import settings
from app.services.strategy_templates import build_signal_func
from app.services.binance_service import binance_service

logger = logging.getLogger(__name__)

# Active strategies to run in paper trading
ACTIVE_STRATEGIES = [
    {
        "strategy_id": "auto_trend_ma",
        "strategy_type": "ma",
        "symbol": "BTCUSDT",
        "interval": "1h",
        "params": {"fast_period": 10, "slow_period": 30},
        "quantity": 0.01,
    },
    {
        "strategy_id": "auto_reversion_rsi",
        "strategy_type": "rsi",
        "symbol": "ETHUSDT",
        "interval": "1h",
        "params": {"rsi_period": 14, "oversold": 30, "overbought": 70},
        "quantity": 0.1,
    },
    {
        "strategy_id": "auto_volatility_boll",
        "strategy_type": "boll",
        "symbol": "SOLUSDT",
        "interval": "1h",
        "params": {"period": 20, "std_dev": 2.0},
        "quantity": 1.0,
    }
]

class StrategyRunnerService:
    def __init__(self):
        self.nc = None
        self.running = False

    async def _connect_nats(self):
        if self.nc and self.nc.is_connected:
            return
        try:
            self.nc = await nats.connect(settings.NATS_URL)
            logger.info("StrategyRunner connected to NATS")
        except Exception as e:
            logger.error(f"Failed to connect to NATS: {e}")

    async def run_all_strategies(self):
        """Fetch data, generate signals, and publish for all active strategies."""
        logger.info(f"Running {len(ACTIVE_STRATEGIES)} automated strategies...")
        await self._connect_nats()
        
        for config in ACTIVE_STRATEGIES:
            try:
                await self._run_single_strategy(config)
            except Exception as e:
                logger.error(f"Error running strategy {config['strategy_id']}: {e}")

    async def _run_single_strategy(self, config: Dict[str, Any]):
        strategy_id = config["strategy_id"]
        strategy_type = config["strategy_type"]
        symbol = config["symbol"]
        interval = config["interval"]
        params = config["params"]
        quantity = config["quantity"]

        # 1. Fetch latest data (OHLCV)
        # Use 100 candles to ensure indicators have enough warmup
        df = await binance_service.get_klines_dataframe(symbol, interval, limit=100)
        if df is None or len(df) < 50:
            logger.warning(f"Insufficient data for {symbol} {interval}")
            return

        # 2. Build signal function and execute
        signal_func = build_signal_func(strategy_type, params)
        
        import inspect
        if inspect.iscoroutinefunction(signal_func):
            signals = await signal_func(df)
        else:
            signals = signal_func(df)

        # 3. Check latest signal (last row)
        latest_signal = int(signals.iloc[-1])
        logger.debug(f"Strategy {strategy_id} signal for {symbol}: {latest_signal}")

        if latest_signal != 0:
            # 4. Prepare and publish signal
            side = "BUY" if latest_signal == 1 else "SELL"
            current_price = float(df["close"].iloc[-1])
            
            payload = {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "price": current_price,
                "strategy_id": strategy_id,
                "order_type": "MARKET",
                "client_order_id": f"auto-{strategy_id}-{int(datetime.now(timezone.utc).timestamp())}"
            }
            
            if self.nc:
                await self.nc.publish("trade.signal", json.dumps(payload).encode())
                logger.info(f"Published {side} signal for {strategy_id} ({symbol}) @ {current_price}")

strategy_runner_service = StrategyRunnerService()
