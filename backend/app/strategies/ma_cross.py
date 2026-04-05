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
                
                # 全仓模式（与 SignalBasedStrategy 对齐）
                # 如果用户显式设置了 quantity 且 > 0，使用固定数量；否则使用初始资金计算
                fixed_qty = self.parameters.get("quantity", 0)
                if fixed_qty and float(fixed_qty) > 0:
                    quantity = float(fixed_qty)
                else:
                    balance_info = await self.bus.get_balance()
                    available_capital = balance_info.get("available_balance", 0)
                    if available_capital <= 0 or bar.close <= 0:
                        return
                        
                    initial_capital = self.parameters.get("initial_capital", available_capital)
                    use_capital = min(initial_capital, available_capital)
                    
                    commission_rate = 0.001    # 与 paper_trading_service FEE_RATE 对齐
                    slippage_pct = 0.0005      # 与 paper_trading_service SLIPPAGE_PCT 对齐
                    effective_price = bar.close * (1 + slippage_pct)
                    quantity = use_capital / (effective_price * (1 + commission_rate))
                    if quantity <= 0:
                        return
                
                order_req = OrderRequest(
                    symbol=bar.symbol,
                    side=TradeSide.BUY,
                    quantity=quantity,
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
