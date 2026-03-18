"""
Signal-Based Strategy Adapter
Wraps the signal functions from strategy_templates into the BaseStrategy interface.
Supports all strategy types: ma, rsi, boll, macd, ema_triple, atr_trend, turtle, ichimoku, smart_beta, basis
"""

import pandas as pd
from typing import Dict, Any, Optional
from app.core.strategy import BaseStrategy
from app.models.trading import BarData, OrderRequest, TradeSide, OrderType
from app.services.strategy_templates import build_signal_func


class SignalBasedStrategy(BaseStrategy):
    """
    A generic strategy that wraps signal functions from strategy_templates.
    Each strategy type (ma, rsi, boll, etc.) generates signals based on indicators.
    """
    def __init__(self, strategy_id: str, bus: 'TradingBus', strategy_type: str = "ma"):
        super().__init__(strategy_id, bus)
        self.strategy_type = strategy_type
        self.bars = []
        self.position = 0.0
        self._signal_func = None
        
    def set_parameters(self, params: Dict[str, Any]):
        super().set_parameters(params)
        # Build the signal function with baked parameters
        try:
            self._signal_func = build_signal_func(self.strategy_type, params)
        except Exception as e:
            self.log(f"Failed to build signal function: {e}", "ERROR")
            self._signal_func = None

    async def on_bar(self, bar: BarData):
        self.bars.append(bar)
        
        # Keep enough bars for the strategy (max 200 for safety)
        max_period = 200
        if len(self.bars) > max_period:
            self.bars.pop(0)

        # Need minimum bars for indicator calculation
        min_bars = self._get_min_bars_required()
        if len(self.bars) < min_bars:
            return

        # Generate signal
        if self._signal_func is None:
            return
            
        try:
            # Convert bars to DataFrame for indicator calculation
            df = pd.DataFrame([{
                'timestamp': b.datetime,
                'open': b.open,
                'high': b.high,
                'low': b.low,
                'close': b.close,
                'volume': getattr(b, 'volume', 0)
            } for b in self.bars])
            df.set_index('timestamp', inplace=True)
            
            # Generate signal
            signal = self._signal_func(df)
            
            if signal is None or len(signal) == 0:
                return
                
            current_signal = signal.iloc[-1]
            
            # Execute based on signal
            if current_signal == 1 and self.position == 0:
                # Buy signal
                self.log(f"BUY signal detected at {bar.close}")
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
                    
            elif current_signal == -1 and self.position > 0:
                # Sell signal
                self.log(f"SELL signal detected at {bar.close}")
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
                    
        except Exception as e:
            self.log(f"Signal generation error: {e}", "ERROR")
            
    def _get_min_bars_required(self) -> int:
        """Return minimum bars needed for each strategy type."""
        min_bars_map = {
            "ma": 60,          # slow_period default 30 + buffer
            "rsi": 30,          # rsi_period 14 + buffer
            "boll": 40,         # period 20 + buffer
            "macd": 50,         # slow=26 + buffer
            "ema_triple": 100,  # slow_period 60 + buffer
            "atr_trend": 50,    # atr_period 14 + trend_period 20
            "turtle": 50,       # entry_period 20 + exit_period 10 + buffer
            "ichimoku": 80,     # senkou_b_period 52 + buffer
            "smart_beta": 5,    # Uses current data only
            "basis": 5,         # Uses current data only
        }
        return min_bars_map.get(self.strategy_type, 30)

    async def on_tick(self, tick):
        # Optional tick-level logic
        pass
