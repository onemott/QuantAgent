import logging
import asyncio
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime
from abc import ABC, abstractmethod
from enum import Enum
from dataclasses import dataclass

from app.models.trading import (
    BarData,
    TickData,
    OrderRequest,
    OrderResult,
    TradeSide,
    OrderType,
    OrderStatus,
)
from app.services.binance_service import binance_service
from app.services.paper_trading_service import paper_trading_service
from app.services.risk_manager import risk_manager
from app.services.clickhouse_service import clickhouse_service

logger = logging.getLogger(__name__)


class TradingMode(str, Enum):
    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"
    HISTORICAL_REPLAY = "historical_replay"


@dataclass
class ReplayConfig:
    start_time: datetime
    end_time: datetime
    speed: int  # (1, 10, 60, 100)
    initial_capital: float
    equity_snapshot_interval: int = 3600  # 权益快照间隔（秒），默认3600（1小时）


class TradingBus(ABC):
    """
    The Data and Execution Bus.
    Adapts data and routes execution based on the current mode (Backtest/Paper).
    """

    @abstractmethod
    async def execute_order(self, order_req: OrderRequest) -> OrderResult:
        """Route order to the appropriate execution interface"""
        pass

    @abstractmethod
    def get_mode(self) -> str:
        """Return 'BACKTEST', 'PAPER', 'LIVE' or 'HISTORICAL_REPLAY'"""
        pass

    @abstractmethod
    def subscribe_bars(self, callback: Callable):
        """Subscribe to K-line bars"""
        pass

    @abstractmethod
    def subscribe_ticks(self, callback: Callable):
        """Subscribe to ticks"""
        pass

    @abstractmethod
    async def publish_bar(self, bar: BarData):
        """Publish a new K-line bar to the bus"""
        pass

    @abstractmethod
    async def publish_tick(self, tick: TickData):
        """Publish a new tick to the bus"""
        pass

    @abstractmethod
    async def jump_to(self, timestamp: datetime):
        """Jump to a specific timestamp in historical replay mode"""
        pass

    @abstractmethod
    def pause(self):
        """Pause the replay"""
        pass

    @abstractmethod
    def resume(self):
        """Resume the replay"""
        pass

    @abstractmethod
    def stop(self):
        """Stop the replay"""
        pass

    @abstractmethod
    async def get_balance(self) -> Dict[str, Any]:
        """Get current account balance"""
        pass


class DataAdapter(ABC):
    """Abstract data adapter for both history and real-time"""

    @abstractmethod
    async def subscribe(self, symbols: List[str], interval: str, callback: Callable):
        """Subscribe to market data and push to callback"""
        pass

    @abstractmethod
    async def get_history(
        self, symbol: str, interval: str, start: datetime, end: datetime
    ) -> List[BarData]:
        """Fetch historical data"""
        pass


class ExecutionRouter(ABC):
    """Abstract execution router for both backtest and paper/live"""

    @abstractmethod
    async def execute(
        self,
        order_req: OrderRequest,
        mode: str = "paper",
        session_id: Optional[str] = None,
    ) -> OrderResult:
        """Execute order and return result"""
        pass

    def set_simulated_time(self, timestamp: datetime):
        """Set simulated time for the router (if supported)"""
        pass


class BacktestDataAdapter(DataAdapter):
    """Fetch historical K-lines from ClickHouse for backtesting"""

    async def subscribe(self, symbols: List[str], interval: str, callback: Callable):
        # In backtesting, "subscription" is a sequential replay of history
        # This will be handled by the backtest engine loop
        pass

    async def get_history(
        self, symbol: str, interval: str, start: datetime, end: datetime
    ) -> List[BarData]:
        df = await clickhouse_service.get_klines_dataframe(symbol, interval, start, end)
        if df is None:
            return []

        bars = []
        for dt, row in df.iterrows():
            bars.append(
                BarData(
                    symbol=symbol,
                    datetime=dt,
                    open=row["open"],
                    high=row["high"],
                    low=row["low"],
                    close=row["close"],
                    volume=row["volume"],
                    interval=interval,
                )
            )
        return bars


class LiveDataAdapter(DataAdapter):
    """Poll Binance for real-time K-lines (Paper/Live mode)"""

    def __init__(self, poll_interval: int = 10):
        self.poll_interval = poll_interval
        self.running = False

    async def subscribe(self, symbols: List[str], interval: str, callback: Callable):
        self.running = True
        last_times = {symbol: None for symbol in symbols}

        while self.running:
            for symbol in symbols:
                try:
                    # Fetch latest bar
                    klines = await binance_service.get_klines(
                        symbol, timeframe=interval, limit=2
                    )
                    if not klines:
                        continue

                    latest_kline = klines[-1]
                    if last_times[symbol] != latest_kline.timestamp:
                        last_times[symbol] = latest_kline.timestamp
                        bar = BarData(
                            symbol=symbol,
                            datetime=latest_kline.timestamp,
                            open=latest_kline.open,
                            high=latest_kline.high,
                            low=latest_kline.low,
                            close=latest_kline.close,
                            volume=latest_kline.volume,
                            interval=interval,
                        )
                        # Push to strategy
                        await callback(bar)
                except Exception as e:
                    logger.error(f"Error polling data for {symbol}: {e}")

            await asyncio.sleep(self.poll_interval)


class PaperExecutionRouter(ExecutionRouter):
    """Route orders to the PaperTradingService (simulated brokerage)"""

    def set_simulated_time(self, timestamp: datetime):
        """Pass simulated time to the paper trading service and risk manager"""
        paper_trading_service.set_simulated_time(timestamp)
        risk_manager.set_simulated_time(timestamp)

    async def execute(
        self,
        order_req: OrderRequest,
        mode: str = "paper",
        session_id: Optional[str] = None,
    ) -> OrderResult:
        try:
            res = await paper_trading_service.create_order(
                symbol=order_req.symbol,
                side=order_req.side,
                quantity=order_req.quantity,
                price=order_req.price if order_req.price else 0.0,
                order_type=order_req.order_type,
                benchmark_price=order_req.benchmark_price,  # Pass benchmark_price
                strategy_id=order_req.strategy_id,
                client_order_id=order_req.client_order_id,
                mode=mode,
                session_id=session_id,
            )

            return OrderResult(
                order_id=res["order_id"],
                client_order_id=order_req.client_order_id,
                symbol=order_req.symbol,
                status=OrderStatus(res["status"]),
                filled_quantity=res.get("quantity", 0.0),
                filled_price=res.get("price", 0.0),
                fee=res.get("fee", 0.0),
                pnl=res.get("pnl"),
                timestamp=datetime.fromisoformat(res["created_at"]),
            )
        except Exception as e:
            logger.error(f"Paper execution failed: {e}")
            return OrderResult(
                order_id="ERROR",
                client_order_id=order_req.client_order_id,
                symbol=order_req.symbol,
                status=OrderStatus.REJECTED,
                timestamp=paper_trading_service._get_current_time(),
                error_msg=str(e),
            )


class BacktestExecutionRouter(ExecutionRouter):
    """Simulate execution for backtesting (ideal match or with slippage)"""

    def __init__(self, slippage_pct: float = 0.0005, fee_rate: float = 0.001):
        self.slippage_pct = slippage_pct
        self.fee_rate = fee_rate
        self.current_bar: Optional[BarData] = None

    def set_current_bar(self, bar: BarData):
        self.current_bar = bar

    async def execute(
        self,
        order_req: OrderRequest,
        mode: str = "backtest",
        session_id: Optional[str] = None,
    ) -> OrderResult:
        if not self.current_bar:
            raise ValueError("No current bar for backtest execution")

        # Simple backtest execution: fill at current bar's close price + slippage
        exec_price = self.current_bar.close
        if order_req.side == TradeSide.BUY:
            exec_price *= 1 + self.slippage_pct
        else:
            exec_price *= 1 - self.slippage_pct

        fee = order_req.quantity * exec_price * self.fee_rate

        return OrderResult(
            order_id=f"BT-{datetime.utcnow().timestamp()}",
            client_order_id=order_req.client_order_id,
            symbol=order_req.symbol,
            status=OrderStatus.FILLED,
            filled_quantity=order_req.quantity,
            filled_price=exec_price,
            fee=fee,
            timestamp=self.current_bar.datetime,
        )


class TradingBusImpl(TradingBus):
    """The concrete implementation of the Trading Bus"""

    def __init__(
        self,
        mode: str,
        data_adapter: Optional[DataAdapter],
        execution_router: ExecutionRouter,
        session_id: Optional[str] = None,
    ):
        self.mode = mode.upper()  # "BACKTEST" or "PAPER"
        self.data_adapter = data_adapter
        self.execution_router = execution_router
        self.session_id = session_id
        self.jump_timestamp: Optional[datetime] = None
        self.current_simulated_time: Optional[datetime] = None
        self.bar_subscribers: List[Callable] = []
        self.tick_subscribers: List[Callable] = []

    def get_mode(self) -> str:
        return self.mode

    def subscribe_bars(self, callback: Callable):
        self.bar_subscribers.append(callback)

    def subscribe_ticks(self, callback: Callable):
        self.tick_subscribers.append(callback)

    async def publish_bar(self, bar: BarData):
        self.current_simulated_time = bar.datetime
        if self.mode == "HISTORICAL_REPLAY":
            self.execution_router.set_simulated_time(bar.datetime)
        tasks = [callback(bar) for callback in self.bar_subscribers]
        if tasks:
            await asyncio.gather(*tasks)

    async def publish_tick(self, tick: TickData):
        self.current_simulated_time = tick.datetime
        if self.mode == "HISTORICAL_REPLAY":
            self.execution_router.set_simulated_time(tick.datetime)
        tasks = [callback(tick) for callback in self.tick_subscribers]
        if tasks:
            await asyncio.gather(*tasks)

    async def jump_to(self, timestamp: datetime):
        """Jump to a specific timestamp in historical replay mode"""
        self.jump_timestamp = timestamp
        self.current_simulated_time = timestamp
        if hasattr(self.data_adapter, "set_start_timestamp"):
            self.data_adapter.set_start_timestamp(timestamp)
        if self.mode == "HISTORICAL_REPLAY":
            self.execution_router.set_simulated_time(timestamp)
        logger.info(f"TradingBus jumped to {timestamp}")

    def pause(self):
        """Pause the replay"""
        if hasattr(self.data_adapter, "pause_playback"):
            self.data_adapter.pause_playback()
            logger.info("TradingBus paused")

    def resume(self):
        """Resume the replay"""
        if hasattr(self.data_adapter, "resume_playback"):
            self.data_adapter.resume_playback()
            logger.info("TradingBus resumed")

    def stop(self):
        """Stop the replay"""
        if hasattr(self.data_adapter, "stop_playback"):
            self.data_adapter.stop_playback()
            logger.info("TradingBus stopped")
        if self.mode == "HISTORICAL_REPLAY":
            self.execution_router.set_simulated_time(None)

    async def execute_order(self, order_req: OrderRequest) -> OrderResult:
        return await self.execution_router.execute(
            order_req, mode=self.mode.lower(), session_id=self.session_id
        )

    async def get_balance(self) -> Dict[str, Any]:
        """Get current account balance from paper trading service"""
        return await paper_trading_service.get_balance(session_id=self.session_id)
