import pandas as pd
import numpy as np
import asyncio
from typing import Dict, Any, List

from app.services.backtester.optimizer import OptunaOptimizer
from app.services.walk_forward.window_manager import WindowManager
from app.services.walk_forward.stability_analyzer import StabilityAnalyzer
from app.services.strategy_templates import build_signal_func
from app.services.backtester.vectorized import VectorizedBacktester

class WalkForwardOptimizer:
    """
    Walk-Forward Optimization (WFO).
    Splits data into rolling In-Sample (IS) and Out-of-Sample (OOS) windows.
    Optimizes parameters on IS and validates on OOS to prevent overfitting.
    Uses WindowManager for window generation and StabilityAnalyzer for evaluation.
    """
    def __init__(self, df: pd.DataFrame, strategy_type: str, initial_capital: float = 10000.0):
        self.df = df
        self.strategy_type = strategy_type
        self.initial_capital = initial_capital

    async def run_wfo(
        self, 
        is_days: int = 180, 
        oos_days: int = 60, 
        n_trials: int = 30,
        use_numba: bool = False,
        embargo_days: int = 0
    ) -> Dict[str, Any]:
        """
        Run WFO across the entire dataset using WindowManager and StabilityAnalyzer.
        Also stitches OOS equity curve.
        """
        if self.df.empty:
            return {"error": "Empty dataframe"}

        # 1. Use WindowManager to generate windows
        window_manager = WindowManager(
            method='rolling',
            train_size=pd.Timedelta(days=is_days),
            test_size=pd.Timedelta(days=oos_days),
            step_size=pd.Timedelta(days=oos_days),
            embargo_size=pd.Timedelta(days=embargo_days)
        )
        
        windows = window_manager.generate_windows(self.df.index)
        
        results = []
        wfo_results_for_analyzer = []
        
        # For OOS equity curve stitching
        stitched_equity_curve = []
        stitched_dates = []
        current_capital = self.initial_capital
        
        for i, window in enumerate(windows):
            train_start, train_end = window['train']
            test_start, test_end = window['test']
            
            is_df = self.df.loc[train_start:train_end]
            if len(is_df) < 20:
                continue
                
            # IS Optimization
            opt = OptunaOptimizer(is_df, self.strategy_type, self.initial_capital)
            opt_res = await asyncio.to_thread(opt.optimize, n_trials=n_trials, use_numba=use_numba)
            best_params = opt_res["best_params"]
            
            # OOS Validation
            oos_df = self.df.loc[test_start:test_end]
            if oos_df.empty:
                continue
                
            signal_func = build_signal_func(self.strategy_type, best_params)
            
            # Use full data up to test_end to avoid indicator warmup period loss in OOS
            full_df = self.df.loc[:test_end]
            
            # To get the first day's return correctly, we need the last day of the previous period
            # So we prepend 1 day to oos_df if possible
            prev_idx = self.df.index.get_indexer([test_start], method='bfill')[0] - 1
            if prev_idx >= 0:
                actual_oos_start = self.df.index[prev_idx]
            else:
                actual_oos_start = test_start
                
            oos_df_bt = self.df.loc[actual_oos_start:test_end]
            
            def oos_signal_wrapper(df_for_bt: pd.DataFrame) -> pd.Series:
                import inspect
                signals = signal_func(full_df)
                # In vectorized mode, signals is mostly synchronous Series
                # If it's a coroutine, we can't easily await it synchronously in pandas.
                # The VectorizedBacktester handles awaiting the outer function if needed, 
                # but here we are wrapping it. If build_signal_func returns a sync function,
                # it's fine. In this codebase, build_signal_func returns a sync Callable.
                return signals.loc[df_for_bt.index]
                
            # Run backtest with `current_capital`
            bt = VectorizedBacktester(oos_df_bt, oos_signal_wrapper, current_capital)
            oos_perf = bt.run()
            
            # Slice out the prepended day if we added one
            if actual_oos_start < test_start:
                oos_equity = oos_perf.get("equity_curve", [])[1:]
                oos_returns_list = oos_perf.get("returns", [])[1:]
                oos_dates = oos_df_bt.index.tolist()[1:]
            else:
                oos_equity = oos_perf.get("equity_curve", [])
                oos_returns_list = oos_perf.get("returns", [])
                oos_dates = oos_df_bt.index.tolist()
                
            if oos_equity:
                stitched_equity_curve.extend(oos_equity)
                stitched_dates.extend(oos_dates)
                current_capital = oos_equity[-1]
                
            # For StabilityAnalyzer, we need returns as pd.Series
            oos_returns = pd.Series(oos_returns_list, index=oos_dates) if oos_returns_list else pd.Series(dtype=float)
            
            # IS returns
            def is_signal_wrapper(df_for_bt: pd.DataFrame) -> pd.Series:
                full_is_df = self.df.loc[:train_end]
                signals = signal_func(full_is_df)
                return signals.loc[df_for_bt.index]

            is_bt = VectorizedBacktester(is_df, is_signal_wrapper, self.initial_capital)
            is_perf = is_bt.run()
            is_returns_list = is_perf.get("returns", [])
            is_returns = pd.Series(is_returns_list, index=is_df.index) if is_returns_list else pd.Series(dtype=float)

            
            wfo_results_for_analyzer.append({
                'is_returns': is_returns,
                'oos_returns': oos_returns,
                'optimal_params': best_params
            })
            
            results.append({
                "window_index": i,
                "is_period": [train_start.isoformat(), train_end.isoformat()],
                "oos_period": [test_start.isoformat(), test_end.isoformat()],
                "best_params": best_params,
                "is_sharpe": opt_res["best_sharpe"],
                "oos_sharpe": oos_perf.get("sharpe_ratio", 0.0),
                "oos_return": oos_perf.get("total_return", 0.0),
                "oos_drawdown": oos_perf.get("max_drawdown", 0.0)
            })

        # 2. Use StabilityAnalyzer
        stability_report = StabilityAnalyzer.analyze_wfo_results(wfo_results_for_analyzer)
        
        # Assign WFE back to results
        wfe_per_window = stability_report.get('wfe_per_window', [])
        for i, res in enumerate(results):
            if i < len(wfe_per_window):
                res['wfe'] = wfe_per_window[i]
                
        # 3. Stitched OOS performance metrics
        stitched_metrics = {}
        if stitched_equity_curve:
            total_return = (stitched_equity_curve[-1] / self.initial_capital - 1) * 100
            
            # Max Drawdown
            eq_series = pd.Series(stitched_equity_curve)
            rolling_max = eq_series.cummax()
            drawdown = (eq_series - rolling_max) / rolling_max
            max_drawdown = abs(float(drawdown.min())) * 100
            
            # Annual Return
            if len(stitched_dates) > 0:
                n_days = (stitched_dates[-1] - stitched_dates[0]).days
                if n_days > 0:
                    annual_return = ((1 + total_return / 100) ** (365 / n_days) - 1) * 100
                else:
                    annual_return = 0.0
            else:
                annual_return = 0.0
                
            # Sharpe Ratio
            all_oos_returns_list = []
            for res in wfo_results_for_analyzer:
                all_oos_returns_list.extend(res['oos_returns'].tolist())
            excess_returns = pd.Series(all_oos_returns_list) - (0.02 / 365)
            if excess_returns.std() > 0:
                sharpe_ratio = float((excess_returns.mean() / excess_returns.std()) * np.sqrt(365))
            else:
                sharpe_ratio = 0.0
            
            stitched_metrics = {
                "total_return": total_return,
                "annual_return": annual_return,
                "max_drawdown": max_drawdown,
                "sharpe_ratio": sharpe_ratio,
                "final_capital": stitched_equity_curve[-1],
                "equity_curve": stitched_equity_curve,
                "dates": [d.isoformat() for d in stitched_dates]
            }

        # Handle stability_report numpy types (like float64) which are not JSON serializable
        # We can just return it, fastapi jsonable_encoder handles standard python types, we might need to convert
        # parameter_stability_scores
        param_scores = stability_report.get("parameter_stability_scores", {})
        for k, v in param_scores.items():
            if isinstance(v, (np.float64, np.float32)):
                param_scores[k] = float(v)
        stability_report["parameter_stability_scores"] = param_scores

        return {
            "strategy": self.strategy_type,
            "walk_forward_results": results,
            "stability_analysis": stability_report,
            "stitched_oos_performance": stitched_metrics,
            "metrics": {
                "avg_oos_sharpe": round(np.mean([r["oos_sharpe"] for r in results]) if results else 0.0, 2),
                "total_oos_return": round(np.sum([r["oos_return"] for r in results]) if results else 0.0, 4),
                "num_windows": len(results)
            }
        }
