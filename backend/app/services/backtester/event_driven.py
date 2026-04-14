import numpy as np
import pandas as pd
from numba import njit, float64, int64
from typing import Dict, Any, List, Tuple

from app.services.backtester.annualization import annualize_return, annualize_sharpe, infer_annualization_factor
from app.services.backtester.signal_resolution import resolve_signal_output

@njit(cache=True)
def _numba_core_loop(
    prices: np.ndarray, 
    signals: np.ndarray, 
    initial_capital: float, 
    commission: float
):
    n = len(prices)
    equity = np.zeros(n, dtype=np.float64)
    capital = initial_capital
    position = 0.0
    entry_price = 0.0
    
    # Pre-allocate trades array (max possible trades = n)
    # Format: [entry_idx, exit_idx, entry_price, exit_price, pnl, pnl_pct, quantity]
    trades = np.zeros((n, 7), dtype=np.float64) 
    trades_count = 0
    total_commission = 0.0
    
    entry_idx = -1
    
    for i in range(n):
        price = prices[i]
        signal = signals[i]
        
        # Calculate Equity
        if position > 0:
            current_equity = capital + position * price
        else:
            current_equity = capital
            
        equity[i] = current_equity
        
        # Trading Logic
        # Buy Signal
        if signal == 1 and position == 0 and capital > 0:
            fee = capital * commission
            invest = capital - fee
            position = invest / price
            entry_price = price
            entry_idx = i
            total_commission += fee
            capital = 0.0
            
        # Sell Signal
        elif signal == -1 and position > 0:
            gross = position * price
            fee = gross * commission
            net = gross - fee
            total_commission += fee
            
            pnl = net - (entry_price * position * (1 + commission)) # Simplified PnL
            pnl_pct = (price / entry_price - 1) * 100 - commission * 200 # Approx
            
            trades[trades_count, 0] = entry_idx
            trades[trades_count, 1] = i
            trades[trades_count, 2] = entry_price
            trades[trades_count, 3] = price
            trades[trades_count, 4] = pnl
            trades[trades_count, 5] = pnl_pct
            trades[trades_count, 6] = position
            trades_count += 1
            
            capital = net
            position = 0.0
            entry_price = 0.0
            entry_idx = -1
            
    # Force close at end
    if position > 0:
        price = prices[-1]
        fee = position * price * commission
        net = position * price - fee
        total_commission += fee
        pnl = net - (entry_price * position * (1 + commission))
        pnl_pct = (price / entry_price - 1) * 100 - commission * 200
        
        trades[trades_count, 0] = entry_idx
        trades[trades_count, 1] = n-1
        trades[trades_count, 2] = entry_price
        trades[trades_count, 3] = price
        trades[trades_count, 4] = pnl
        trades[trades_count, 5] = pnl_pct
        trades[trades_count, 6] = position
        trades_count += 1
        
        capital = net
        position = 0.0
        equity[-1] = capital
        
    return equity, trades[:trades_count], total_commission, capital

class EventDrivenBacktester:
    """
    Event-Driven Backtester using Numba for high-performance loops (L2).
    Suitable for path-dependent strategies and complex logic.
    """
    def __init__(
        self, 
        df: pd.DataFrame, 
        signal_func, 
        initial_capital: float = 10000.0, 
        commission: float = 0.001
    ):
        self.df = df.copy()
        self.signal_func = signal_func
        self.initial_capital = initial_capital
        self.commission = commission

    def run(self) -> Dict[str, Any]:
        signals = resolve_signal_output(self.signal_func(self.df))
        
        # 2. Prepare Data for Numba
        # Ensure contiguous arrays of correct type
        prices = self.df['close'].values.astype(np.float64)
        # Handle NaN in signals if any
        sigs = signals.fillna(0).values.astype(np.int64)
        shifted_sigs = np.zeros_like(sigs)
        if len(sigs) > 1:
            shifted_sigs[1:] = sigs[:-1]
        
        # 3. Run Numba Core Loop
        equity, trades_arr, total_commission, final_capital = _numba_core_loop(
            prices, shifted_sigs, self.initial_capital, self.commission
        )
        
        # 4. Process Results
        equity_curve = pd.Series(equity, index=self.df.index)
        
        # Metrics
        total_return = (final_capital / self.initial_capital - 1) * 100
        annualization_factor = infer_annualization_factor(self.df.index)
        returns = equity_curve.pct_change().dropna()
        
        annual_return = annualize_return(
            total_return / 100,
            len(returns),
            annualization_factor
        )
        
        # Max Drawdown
        rolling_max = equity_curve.cummax()
        drawdown = (equity_curve - rolling_max) / rolling_max
        max_drawdown = abs(drawdown.min()) * 100
        
        sharpe_ratio = annualize_sharpe(returns, annualization_factor)
            
        # Trade Stats
        trades_df = pd.DataFrame(trades_arr, columns=['entry_idx', 'exit_idx', 'entry_price', 'exit_price', 'pnl', 'pnl_pct', 'quantity'])
        total_trades = len(trades_df)
        
        if total_trades > 0:
            win_rate = (trades_df['pnl'] > 0).mean() * 100
            avg_win = trades_df[trades_df['pnl'] > 0]['pnl'].mean() if not trades_df[trades_df['pnl'] > 0].empty else 0.0
            avg_loss = abs(trades_df[trades_df['pnl'] < 0]['pnl'].mean()) if not trades_df[trades_df['pnl'] < 0].empty else 0.0
            profit_factor = avg_win / avg_loss if avg_loss > 0 else float('inf')
        else:
            win_rate = 0.0
            profit_factor = 0.0

        # Format trades list
        trades_list = []
        times = self.df.index
        for _, row in trades_df.iterrows():
            trades_list.append({
                "entry_time": str(times[int(row['entry_idx'])])[:19],
                "exit_time": str(times[int(row['exit_idx'])])[:19],
                "entry_price": row['entry_price'],
                "exit_price": row['exit_price'],
                "quantity": row['quantity'],
                "pnl": row['pnl'],
                "pnl_pct": row['pnl_pct']
            })

        return {
            "total_return": total_return,
            "annual_return": annual_return,
            "max_drawdown": max_drawdown,
            "sharpe_ratio": sharpe_ratio,
            "win_rate": win_rate,
            "profit_factor": min(profit_factor, 999.0),
            "total_trades": total_trades,
            "total_commission": total_commission,
            "final_capital": final_capital,
            "equity_curve": equity_curve.tolist(),
            "trades": trades_list
        }
