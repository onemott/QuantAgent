import numpy as np
import pandas as pd
from typing import Dict, Any, Callable

class VectorizedBacktester:
    """
    Vectorized Backtester for fast initial screening (L1).
    Uses pandas/numpy for column-wise operations, avoiding loops.
    """
    def __init__(
        self, 
        df: pd.DataFrame, 
        signal_func: Callable[[pd.DataFrame], pd.Series], 
        initial_capital: float = 10000.0, 
        commission: float = 0.001
    ):
        self.df = df.copy()
        self.signal_func = signal_func
        self.initial_capital = initial_capital
        self.commission = commission

    def run(self) -> Dict[str, Any]:
        # 1. Generate Signals
        signals = self.signal_func(self.df)
        
        # 2. Calculate Returns
        # Return at time t is (Price[t] - Price[t-1]) / Price[t-1]
        returns = self.df['close'].pct_change().fillna(0)
        
        # 3. Align Signals
        # Signal at t-1 determines position at t
        # Shift signals forward by 1
        pos = signals.shift(1).fillna(0)
        
        # 4. Strategy Returns (Gross)
        strategy_returns = pos * returns
        
        # 5. Transaction Costs
        # Cost is incurred when position changes: |pos[t] - pos[t-1]|
        # Cost = |delta_pos| * commission_rate
        pos_diff = pos.diff().abs().fillna(0)
        # Note: Cost is relative to capital/position value. 
        # Simplified: Cost as a percentage deduction from return
        costs = pos_diff * self.commission
        
        # 6. Net Returns
        net_returns = strategy_returns - costs
        
        # 7. Equity Curve
        # Cumulative product of (1 + net_return)
        equity_curve = self.initial_capital * (1 + net_returns).cumprod()
        
        # 8. Metrics Calculation
        final_capital = float(equity_curve.iloc[-1])
        total_return = (final_capital / self.initial_capital - 1) * 100
        
        # Annual Return
        if len(self.df) > 0:
            n_days = (self.df.index[-1] - self.df.index[0]).days
            if n_days > 0:
                annual_return = ((1 + total_return / 100) ** (365 / n_days) - 1) * 100
            else:
                annual_return = 0.0
        else:
            annual_return = 0.0
        
        # Max Drawdown
        rolling_max = equity_curve.cummax()
        drawdown = (equity_curve - rolling_max) / rolling_max
        max_drawdown = abs(float(drawdown.min())) * 100
        
        # Sharpe Ratio
        risk_free_daily = 0.02 / 365
        excess_returns = net_returns - risk_free_daily
        if excess_returns.std() > 0:
            sharpe_ratio = float((excess_returns.mean() / excess_returns.std()) * np.sqrt(365))
        else:
            sharpe_ratio = 0.0
            
        # Win Rate & Trade Stats (Approximate)
        # Identify trades: non-zero pos_diff indicates a trade execution (entry or exit)
        # This is a rough approximation. For accurate trade stats, use EventDriven.
        total_trades = int((pos_diff > 0).sum())
        
        # Return simplified result
        return {
            "total_return": total_return,
            "annual_return": annual_return,
            "max_drawdown": max_drawdown,
            "sharpe_ratio": sharpe_ratio,
            "total_trades": total_trades,
            "final_capital": final_capital,
            "equity_curve": equity_curve.tolist(), # Can be large
            "win_rate": 0.0, # Placeholder, hard to calc accurately in vector mode
            "profit_factor": 0.0 # Placeholder
        }
