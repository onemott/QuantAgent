import numpy as np
import pandas as pd
from typing import Dict, Any, Callable

from app.services.backtester.annualization import annualize_return, annualize_sharpe, infer_annualization_factor
from app.services.backtester.signal_resolution import resolve_signal_output

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
        commission: float = 0.001,
        initial_position: float = 0.0,
        annualization_factor: int | None = None
    ):
        self.df = df.copy()
        self.signal_func = signal_func
        self.initial_capital = initial_capital
        self.commission = commission
        self.initial_position = initial_position
        self.annualization_factor = annualization_factor

    def run(self) -> Dict[str, Any]:
        signals = resolve_signal_output(self.signal_func(self.df))
        
        # 2. Calculate Returns
        # Return at time t is (Price[t] - Price[t-1]) / Price[t-1]
        returns = self.df['close'].pct_change().fillna(0)

        # 3. Convert Sparse Action Signals to Continuous Position State
        # ============================================================
        # 信号语义约定（所有策略必须遵循）：
        #   1 = 买入动作（开多头仓）
        #   -1 = 卖出动作（平仓）
        #   0 = 无动作（保持当前状态）
        #
        # ffill 转换原理：
        #   - 将0替换为NaN，然后使用 ffill() 向前填充最近的非零信号
        #   - 这样买入信号(1)会一直保持直到遇到卖出信号(-1)
        #   - 例如：[..., 0, 1, 0, 0, 0, -1, 0, ...] → [..., NaN, 1, 1, 1, 1, -1, NaN, ...]
        #
        # clip(lower=0) 的原因：
        #   - 当前系统仅支持多头持仓，不支持做空
        #   - 卖出信号(-1)后应变为空仓状态(0)，而非空头(-1)
        #   - clip将所有负值截断为0，确保持仓状态仅为 0（空仓）或 1（多头）
        position = signals.replace(0, np.nan).ffill()
        if len(position) > 0 and pd.isna(position.iloc[0]):
            position.iloc[0] = self.initial_position
            position = position.ffill()
        position = position.fillna(0)
        position = position.clip(lower=0)

        # 4. Align Position with Returns (Avoid Look-Ahead Bias)
        # 使用前一天信号决定今天的持仓，shift(1)避免未来函数偏差
        pos = position.shift(1).fillna(self.initial_position)

        # 5. Strategy Returns (Gross)
        strategy_returns = pos * returns

        # 6. Transaction Costs
        # 手续费在持仓状态变化时扣减：
        #   - pos从0变1：开仓（扣费一次）
        #   - pos从1变0：平仓（扣费一次）
        # 持仓变化点 = 交易发生点，变化幅度固定为1（因为pos只有0和1两种状态）
        trades = pos.diff().fillna(0).abs()
        costs = trades * self.commission
        
        # 7. Net Returns
        net_returns = strategy_returns - costs
        
        # 8. Equity Curve
        # Cumulative product of (1 + net_return)
        equity_curve = self.initial_capital * (1 + net_returns).cumprod()

        # 9. Metrics Calculation
        if len(position) > 0:
            final_position = float(position.iloc[-1])
        else:
            final_position = self.initial_position
            
        final_capital = float(equity_curve.iloc[-1])
        total_return = (final_capital / self.initial_capital - 1) * 100
        annualization_factor = self.annualization_factor or infer_annualization_factor(self.df.index)
        
        annual_return = annualize_return(total_return / 100, max(len(self.df) - 1, 0), annualization_factor)
        
        # Max Drawdown
        rolling_max = equity_curve.cummax()
        drawdown = (equity_curve - rolling_max) / rolling_max
        max_drawdown = abs(float(drawdown.min())) * 100
        
        sharpe_ratio = annualize_sharpe(net_returns, annualization_factor)
            
        # Win Rate & Trade Stats (Approximate)
        # trades 变量记录了所有持仓变化的点（开仓和平仓）
        # 每次完整的买卖周期包含两次变化（开仓+平仓），所以交易对数 = trades_count / 2
        # 这只是近似统计，准确交易统计请使用 EventDriven 引擎
        total_trades = int((trades > 0).sum())
        
        # Return simplified result
        return {
            "total_return": total_return,
            "annual_return": annual_return,
            "max_drawdown": max_drawdown,
            "sharpe_ratio": sharpe_ratio,
            "total_trades": total_trades,
            "final_capital": final_capital,
            "final_position": final_position,
            "equity_curve": equity_curve.tolist(), # Can be large
            "returns": net_returns.tolist(), # Add returns
            "trade_markers": trades.tolist(),
            "win_rate": 0.0, # Placeholder, hard to calc accurately in vector mode
            "profit_factor": 0.0 # Placeholder
        }
