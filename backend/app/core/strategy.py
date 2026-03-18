from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from app.models.trading import BarData, TickData, OrderRequest, OrderResult

class BaseStrategy(ABC):
    """
    Base Strategy class for the "Three-in-One" architecture.
    A single codebase for both backtesting and paper trading.
    """
    def __init__(self, strategy_id: str, bus: 'TradingBus'):
        self.strategy_id = strategy_id
        self.bus = bus
        self.parameters: Dict[str, Any] = {}

    def set_parameters(self, params: Dict[str, Any]):
        self.parameters.update(params)

    @abstractmethod
    async def on_bar(self, bar: BarData):
        """Called when a new K-line bar arrives"""
        pass

    @abstractmethod
    async def on_tick(self, tick: TickData):
        """Called when a new Tick arrives"""
        pass

    async def send_order(self, order_req: OrderRequest) -> OrderResult:
        """Send an order via the bus"""
        order_req.strategy_id = self.strategy_id
        return await self.bus.execute_order(order_req)

    def log(self, message: str, level: str = "INFO"):
        """Logging utility for strategies"""
        print(f"[{level}] [Strategy:{self.strategy_id}] {message}")
