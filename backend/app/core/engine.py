import logging
import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional

from app.core.strategy import BaseStrategy
from app.core.bus import (
    TradingBusImpl, BacktestDataAdapter, BacktestExecutionRouter, 
    PaperExecutionRouter, LiveDataAdapter
)
from app.models.trading import BarData, OrderResult

logger = logging.getLogger(__name__)

class UnifiedEngine:
    """
    The Unified Engine to run strategies in both Backtest and Paper/Live modes.
    Ensures logic consistency across different environments.
    """
    def __init__(self, mode: str, strategy_class: type, strategy_id: str, params: Dict[str, Any] = None):
        self.mode = mode.upper()
        self.strategy_id = strategy_id
        self.strategy_params = params or {}
        
        # 1. Setup adapters based on mode
        if self.mode == "BACKTEST":
            self.data_adapter = BacktestDataAdapter()
            self.execution_router = BacktestExecutionRouter()
        elif self.mode == "HISTORICAL_REPLAY":
            # Historical Replay uses PaperTradingService but with historical data
            # This adapter is not imported yet, will need to import it
            from app.services.historical_replay_adapter import HistoricalReplayAdapter
            from app.core.bus import ReplayConfig
            
            # Create a default ReplayConfig for now, or assume it's passed in
            # For simplicity in initialization, we might need to update this later
            config = ReplayConfig(
                start_time=datetime.utcnow(), 
                end_time=datetime.utcnow(), 
                speed=60, 
                initial_capital=100000.0
            )
            
            # We'll need a way to pass the real config to the engine
            self.execution_router = PaperExecutionRouter()
            self.data_adapter = None # Will be set in run_replay
        else: # PAPER / LIVE
            self.data_adapter = LiveDataAdapter()
            self.execution_router = PaperExecutionRouter()

        # 2. Setup Bus and Strategy
        self.bus = TradingBusImpl(self.mode, self.data_adapter, self.execution_router)
        self.strategy: BaseStrategy = strategy_class(strategy_id, self.bus)
        self.strategy.set_parameters(self.strategy_params)

        # 3. State tracking
        self.equity_curve: List[Dict[str, Any]] = []
        self.trade_history: List[OrderResult] = []

    async def run_backtest(self, symbol: str, interval: str, start: datetime, end: datetime):
        """Run backtest by replaying historical data"""
        if self.mode != "BACKTEST":
            raise ValueError("Engine is not in BACKTEST mode")

        # 1. Fetch data
        bars = await self.data_adapter.get_history(symbol, interval, start, end)
        if not bars:
            logger.warning(f"No historical data for {symbol} {interval} from {start} to {end}")
            return

        logger.info(f"Replaying {len(bars)} bars for strategy {self.strategy_id}...")

        # 2. Replay loop
        for bar in bars:
            # Update execution router state for this bar (to simulate filling at this price)
            self.execution_router.set_current_bar(bar)
            
            # Strategy callback
            await self.strategy.on_bar(bar)
            
            # Track state (simplified equity tracking)
            # In a real system, ExecutionRouter would track balance/positions
            pass

        logger.info(f"Backtest for {self.strategy_id} completed.")

    async def run_paper(self, symbols: List[str], interval: str):
        """Run in paper trading mode by subscribing to live data"""
        if self.mode != "PAPER":
            raise ValueError("Engine is not in PAPER mode")

        logger.info(f"Starting paper trading for {self.strategy_id}...")
        
        # Subscribe to live data via the adapter
        # The adapter will call self.strategy.on_bar internally via the callback
        await self.data_adapter.subscribe(symbols, interval, self.strategy.on_bar)
