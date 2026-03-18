import pandas as pd
from typing import Dict, Any
from app.core.strategy import BaseStrategy
from app.models.trading import BarData, OrderRequest, TradeSide, OrderType

class MaCrossStrategy(BaseStrategy):
    """
    Moving Average Crossover Strategy implementation using the new architecture.
    Same code for backtesting and paper trading.
    """
    def __init__(self, strategy_id: str, bus: 'TradingBus'):
        super().__init__(strategy_id, bus)
        self.bars = []
        self.position = 0.0

    async def on_bar(self, bar: BarData):
        self.bars.append(bar)
        
        # Keep only the last 50 bars to save memory
        if len(self.bars) > 50:
            self.bars.pop(0)

        if len(self.bars) < self.parameters.get("slow_period", 30):
            return

        # Calculate indicators (simplified for example)
        df = pd.DataFrame([b.dict() for b in self.bars])
        fast_ma = df['close'].rolling(window=self.parameters.get("fast_period", 10)).mean().iloc[-1]
        slow_ma = df['close'].rolling(window=self.parameters.get("slow_period", 30)).mean().iloc[-1]
        prev_fast_ma = df['close'].rolling(window=self.parameters.get("fast_period", 10)).mean().iloc[-2]
        prev_slow_ma = df['close'].rolling(window=self.parameters.get("slow_period", 30)).mean().iloc[-2]

        # Buy Signal: Golden Cross
        if prev_fast_ma <= prev_slow_ma and fast_ma > slow_ma:
            if self.position == 0:
                self.log(f"Golden Cross detected at {bar.close}, sending BUY order")
                order_req = OrderRequest(
                    symbol=bar.symbol,
                    side=TradeSide.BUY,
                    quantity=self.parameters.get("quantity", 0.01),
                    price=bar.close,
                    order_type=OrderType.MARKET,
                    strategy_id=self.strategy_id
                )
                res = await self.send_order(order_req)
                if res.status == "FILLED":
                    self.position = res.filled_quantity

        # Sell Signal: Death Cross
        elif prev_fast_ma >= prev_slow_ma and fast_ma < slow_ma:
            if self.position > 0:
                self.log(f"Death Cross detected at {bar.close}, sending SELL order")
                order_req = OrderRequest(
                    symbol=bar.symbol,
                    side=TradeSide.SELL,
                    quantity=self.position,
                    price=bar.close,
                    order_type=OrderType.MARKET,
                    strategy_id=self.strategy_id
                )
                res = await self.send_order(order_req)
                if res.status == "FILLED":
                    self.position = 0

    async def on_tick(self, tick):
        # Optional tick-level logic
        pass
