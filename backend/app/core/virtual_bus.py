import logging
from datetime import datetime
from typing import List, Tuple, Dict, Any, Callable, Optional
from dataclasses import dataclass
import pandas as pd
import numpy as np

from app.core.bus import ExecutionRouter, TradingBus
from app.models.trading import OrderRequest, OrderResult, TradeSide, OrderStatus, BarData, TickData

logger = logging.getLogger(__name__)

@dataclass
class VirtualPerformanceMetric:
    """
    Virtual performance metric compatible with PerformanceMetric ORM model.
    Used for memory-based evaluation in DynamicSelectionStrategy.
    """
    _annualized_return: Optional[float] = 0.0
    _max_drawdown_pct: Optional[float] = 0.0
    _sharpe_ratio: Optional[float] = 0.0
    _win_rate: Optional[float] = 0.0
    _total_trades: Optional[int] = 0
    _total_return: Optional[float] = 0.0
    _volatility: Optional[float] = 0.0
    _sortino_ratio: Optional[float] = 0.0
    _calmar_ratio: Optional[float] = 0.0

    @property
    def annualized_return(self) -> float:
        return float(self._annualized_return or 0.0)

    @property
    def max_drawdown_pct(self) -> float:
        return float(self._max_drawdown_pct or 0.0)

    @property
    def sharpe_ratio(self) -> float:
        return float(self._sharpe_ratio or 0.0)

    @property
    def win_rate(self) -> float:
        return float(self._win_rate or 0.0)

    @property
    def total_trades(self) -> int:
        return int(self._total_trades or 0)

    @property
    def total_return(self) -> float:
        return float(self._total_return or 0.0)

    @property
    def volatility(self) -> float:
        return float(self._volatility or 0.0)

    @property
    def sortino_ratio(self) -> float:
        return float(self._sortino_ratio or 0.0)

    @property
    def calmar_ratio(self) -> float:
        return float(self._calmar_ratio or 0.0)


class VirtualExecutionRouter(ExecutionRouter):
    def __init__(self, initial_capital: float = 10000.0, slippage_pct: float = 0.0005, fee_rate: float = 0.001, max_equity_curve_size: int = 5000):
        self.initial_capital = initial_capital
        self.slippage_pct = slippage_pct
        self.fee_rate = fee_rate
        self.max_equity_curve_size = max_equity_curve_size
        self.cash = initial_capital
        self.position = 0.0
        self.position_avg_price = 0.0
        self.equity_curve: List[Tuple[datetime, float]] = []
        self.trade_count = 0
        self.winning_trades = 0
        self.current_bar: Optional[BarData] = None
        self._last_snapshot_time: Optional[datetime] = None

    def _trim_equity_curve(self):
        """Trim equity_curve to prevent unbounded memory growth."""
        if len(self.equity_curve) > self.max_equity_curve_size:
            # Keep the latter half to preserve recent data for performance calculation
            trim_point = len(self.equity_curve) // 2
            self.equity_curve = self.equity_curve[trim_point:]

    def set_current_bar(self, bar: BarData):
        self.current_bar = bar
        # Record equity snapshot if timestamp changed
        if self._last_snapshot_time != bar.datetime:
            self.equity_curve.append((bar.datetime, self.get_equity()))
            self._trim_equity_curve()
            self._last_snapshot_time = bar.datetime

    def get_equity(self) -> float:
        if self.current_bar:
            return self.cash + self.position * self.current_bar.close
        return self.cash + self.position * self.position_avg_price

    async def execute(
        self,
        order_req: OrderRequest,
        mode: str = "paper",
        session_id: Optional[str] = None,
    ) -> OrderResult:
        if not self.current_bar:
            raise ValueError("No current bar for virtual execution")

        exec_price = self.current_bar.close
        if order_req.side == TradeSide.BUY:
            exec_price *= 1 + self.slippage_pct
        else:
            exec_price *= 1 - self.slippage_pct

        fee = order_req.quantity * exec_price * self.fee_rate

        pnl = 0.0
        if order_req.side == TradeSide.BUY:
            cost = order_req.quantity * exec_price + fee
            
            # Update position_avg_price
            total_value = self.position * self.position_avg_price + order_req.quantity * exec_price
            self.position += order_req.quantity
            self.position_avg_price = total_value / self.position if self.position > 0 else 0.0
            self.cash -= cost
            
        else: # SELL
            proceeds = order_req.quantity * exec_price - fee
            
            # Simple PnL for long position close
            pnl = (exec_price - self.position_avg_price) * order_req.quantity - fee
            if pnl > 0:
                self.winning_trades += 1
                
            self.position -= order_req.quantity
            self.cash += proceeds
            if abs(self.position) <= 1e-8: # Handle float precision
                self.position = 0.0
                self.position_avg_price = 0.0
                
        self.trade_count += 1
        
        # Record equity after trade (can overwrite same timestamp or append)
        self.equity_curve.append((self.current_bar.datetime, self.get_equity()))
        self._trim_equity_curve()
        self._last_snapshot_time = self.current_bar.datetime
        
        return OrderResult(
            order_id=f"VIRT-{self.current_bar.datetime.timestamp()}",
            client_order_id=order_req.client_order_id,
            symbol=order_req.symbol,
            status=OrderStatus.FILLED,
            filled_quantity=order_req.quantity,
            filled_price=exec_price,
            fee=fee,
            pnl=pnl,
            timestamp=self.current_bar.datetime,
        )

    def get_performance_metric(self) -> VirtualPerformanceMetric:
        metric = VirtualPerformanceMetric()
        metric._total_trades = self.trade_count
        if self.trade_count > 0:
            metric._win_rate = self.winning_trades / self.trade_count
            
        if not self.equity_curve:
            return metric
            
        df = pd.DataFrame(self.equity_curve, columns=["datetime", "equity"])
        df.set_index("datetime", inplace=True)
        # Keep last record for each timestamp
        df = df[~df.index.duplicated(keep='last')]
        df.sort_index(inplace=True)
        
        if len(df) < 2:
            total_return = (self.get_equity() - self.initial_capital) / self.initial_capital
            metric._total_return = float(total_return)
            return metric
            
        df['returns'] = df['equity'].pct_change().fillna(0)
        
        total_return = (df['equity'].iloc[-1] - self.initial_capital) / self.initial_capital
        metric._total_return = float(total_return)
        
        duration_days = (df.index[-1] - df.index[0]).total_seconds() / 86400
        annualized_return = 0.0
        if duration_days > 0:
            annualized_return = (1 + total_return) ** (365 / duration_days) - 1
            metric._annualized_return = float(annualized_return)
        
        cummax = df['equity'].cummax()
        drawdown = (df['equity'] - cummax) / cummax
        metric._max_drawdown_pct = float(abs(drawdown.min()))
        
        freq_secs = (df.index[1] - df.index[0]).total_seconds() if len(df) > 1 else 86400
        periods_per_year = 365 * 86400 / freq_secs if freq_secs > 0 else 365
        
        daily_returns = df['returns']
        volatility = daily_returns.std() * np.sqrt(periods_per_year)
        metric._volatility = float(volatility)
        
        risk_free_rate = 0.0
        if volatility > 0:
            metric._sharpe_ratio = float((annualized_return - risk_free_rate) / volatility)
        
        negative_returns = daily_returns[daily_returns < 0]
        downside_std = negative_returns.std() * np.sqrt(periods_per_year) if len(negative_returns) > 0 else 0
        if downside_std > 0:
            metric._sortino_ratio = float((annualized_return - risk_free_rate) / downside_std)
            
        if metric._max_drawdown_pct > 0:
            metric._calmar_ratio = float(annualized_return / metric._max_drawdown_pct)
            
        return metric


class VirtualTradingBus(TradingBus):
    def __init__(self, initial_capital: float = 10000.0):
        self.router = VirtualExecutionRouter(initial_capital=initial_capital)

    async def execute_order(self, order_req: OrderRequest) -> OrderResult:
        return await self.router.execute(order_req, mode="virtual")

    def get_mode(self) -> str:
        return "VIRTUAL"

    def subscribe_bars(self, callback: Callable):
        pass

    def subscribe_ticks(self, callback: Callable):
        pass

    async def publish_bar(self, bar: BarData):
        self.router.set_current_bar(bar)

    async def publish_tick(self, tick: TickData):
        pass

    async def jump_to(self, timestamp: datetime):
        pass

    def pause(self):
        pass

    def resume(self):
        pass

    def stop(self):
        pass

    async def get_balance(self) -> Dict[str, Any]:
        equity = self.router.get_equity()
        cash = self.router.cash
        return {
            "total_balance": equity,
            "available_balance": cash,
            "total_equity": equity,
            "assets": [{"asset": "USDT", "free": cash, "locked": 0.0}]
        }

    def get_equity(self) -> float:
        return self.router.get_equity()

    def get_performance_metric(self) -> VirtualPerformanceMetric:
        return self.router.get_performance_metric()

