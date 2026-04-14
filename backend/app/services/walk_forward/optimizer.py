import pandas as pd
import numpy as np
import asyncio
from typing import Dict, Any, List

from app.services.backtester.optimizer import OptunaOptimizer
from app.services.backtester.annualization import annualize_return, annualize_sharpe, infer_annualization_factor, validate_datetime_index
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

    @staticmethod
    def _build_visible_oos_performance(
        raw_performance: Dict[str, Any],
        visible_offset: int,
        initial_capital: float,
        annualization_factor: int
    ) -> Dict[str, Any]:
        equity_curve = raw_performance.get("equity_curve", [])
        returns = raw_performance.get("returns", [])
        trade_markers = raw_performance.get("trade_markers", [])

        visible_equity = equity_curve[visible_offset:]
        visible_returns = returns[visible_offset:]
        visible_trades = trade_markers[visible_offset:]
        visible_start_capital = float(equity_curve[visible_offset - 1]) if visible_offset > 0 and equity_curve else initial_capital

        if visible_equity:
            final_capital = float(visible_equity[-1])
            total_return = (final_capital / visible_start_capital - 1) * 100 if visible_start_capital > 0 else 0.0
            annual_return = annualize_return(total_return / 100, len(visible_returns), annualization_factor)
            sharpe_ratio = annualize_sharpe(pd.Series(visible_returns, dtype=float), annualization_factor)
            equity_series = pd.Series(visible_equity, dtype=float)
            rolling_max = equity_series.cummax()
            drawdown = (equity_series - rolling_max) / rolling_max
            max_drawdown = abs(float(drawdown.min())) * 100
        else:
            final_capital = float(visible_start_capital)
            total_return = 0.0
            annual_return = 0.0
            sharpe_ratio = 0.0
            max_drawdown = 0.0

        total_trades = int((pd.Series(visible_trades, dtype=float) > 0).sum()) if visible_trades else 0

        return {
            "total_return": total_return,
            "annual_return": annual_return,
            "max_drawdown": max_drawdown,
            "sharpe_ratio": sharpe_ratio,
            "total_trades": total_trades,
            "final_capital": final_capital,
            "final_position": raw_performance.get("final_position", 0.0),
            "equity_curve": visible_equity,
            "returns": visible_returns,
        }

    async def run_wfo(
        self, 
        is_days: int = 180, 
        oos_days: int = 60, 
        step_days: int | None = None,
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
        try:
            validate_datetime_index(self.df.index, "Walk-forward data")
            annualization_factor = infer_annualization_factor(self.df.index)
        except ValueError as exc:
            return {"error": str(exc)}

        # 1. Use WindowManager to generate windows
        window_manager = WindowManager(
            method='rolling',
            train_size=pd.Timedelta(days=is_days),
            test_size=pd.Timedelta(days=oos_days),
            step_size=pd.Timedelta(days=step_days or oos_days),
            embargo_size=pd.Timedelta(days=embargo_days)
        )
        
        windows = window_manager.generate_windows(self.df.index)
        if not windows:
            return {"error": "No valid walk-forward windows were generated for the requested configuration."}
        
        results = []
        wfo_results_for_analyzer = []
        
        # For OOS equity curve stitching
        stitched_equity_curve = []
        stitched_dates = []
        current_capital = self.initial_capital
        current_position = 0.0
        last_test_end_idx = None
        
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
            
            full_df = self.df.loc[:test_end]

            test_start_idx = self.df.index.get_indexer([test_start])[0]
            test_end_idx = self.df.index.get_indexer([test_end])[0]
            backtest_start_idx = max(test_start_idx - 1, 0) if last_test_end_idx is None else last_test_end_idx
            visible_offset = test_start_idx - backtest_start_idx
            oos_df_bt = self.df.iloc[backtest_start_idx:test_end_idx + 1]
            
            def oos_signal_wrapper(df_for_bt: pd.DataFrame) -> pd.Series:
                signals = signal_func(full_df)
                return signals.loc[df_for_bt.index]
                
            # Run backtest with `current_capital`
            bt = VectorizedBacktester(
                oos_df_bt, 
                oos_signal_wrapper, 
                current_capital, 
                initial_position=current_position,
                annualization_factor=annualization_factor
            )
            raw_oos_perf = await asyncio.to_thread(bt.run)
            oos_perf = self._build_visible_oos_performance(
                raw_oos_perf,
                visible_offset,
                current_capital,
                annualization_factor
            )
            current_position = raw_oos_perf.get("final_position", 0.0)

            oos_equity = oos_perf.get("equity_curve", [])
            oos_returns_list = oos_perf.get("returns", [])
            oos_dates = oos_df_bt.index.tolist()[visible_offset:]
                
            if oos_equity:
                stitched_equity_curve.extend(oos_equity)
                stitched_dates.extend(oos_dates)
                current_capital = oos_equity[-1]
            last_test_end_idx = test_end_idx
                
            # For StabilityAnalyzer, we need returns as pd.Series
            oos_returns = pd.Series(oos_returns_list, index=oos_dates) if oos_returns_list else pd.Series(dtype=float)
            
            # IS returns
            def is_signal_wrapper(df_for_bt: pd.DataFrame) -> pd.Series:
                full_is_df = self.df.loc[:train_end]
                signals = signal_func(full_is_df)
                return signals.loc[df_for_bt.index]

            is_bt = VectorizedBacktester(
                is_df,
                is_signal_wrapper,
                self.initial_capital,
                annualization_factor=annualization_factor
            )
            is_perf = await asyncio.to_thread(is_bt.run)
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
                "is_return": is_perf.get("total_return", 0.0),
                "oos_sharpe": oos_perf.get("sharpe_ratio", 0.0),
                "oos_return": oos_perf.get("total_return", 0.0),
                "oos_drawdown": oos_perf.get("max_drawdown", 0.0),
                "oos_trades": oos_perf.get("total_trades", 0)
            })

        if not results:
            return {"error": "Walk-forward optimization produced no valid windows. Please expand the dataset or adjust the window settings."}

        # 2. Use StabilityAnalyzer
        stability_report = StabilityAnalyzer.analyze_wfo_results(
            wfo_results_for_analyzer, 
            annualization_factor=annualization_factor
        )
        
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
            
            all_oos_returns_list = []
            for res in wfo_results_for_analyzer:
                all_oos_returns_list.extend(res['oos_returns'].tolist())
            annual_return = annualize_return(total_return / 100, len(all_oos_returns_list), annualization_factor)
            sharpe_ratio = annualize_sharpe(pd.Series(all_oos_returns_list, dtype=float), annualization_factor)
            
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

        # Extract overall_wfe from stability_analysis
        overall_wfe = stability_report.get("average_wfe", 0.0)
        if isinstance(overall_wfe, (np.float64, np.float32)):
            overall_wfe = float(overall_wfe)
        
        # Get avg_oos_annual_return from stitched_oos_performance
        avg_oos_annual_return = stitched_metrics.get("annual_return", 0.0)
        
        # Sum up all OOS trades
        total_oos_trades = int(np.sum([r.get("oos_trades", 0) for r in results]))
        
        return {
            "strategy": self.strategy_type,
            "walk_forward_results": results,
            "stability_analysis": stability_report,
            "stitched_oos_performance": stitched_metrics,
            "metrics": {
                "avg_oos_sharpe": round(np.mean([r["oos_sharpe"] for r in results]) if results else 0.0, 2),
                "total_oos_return": round(stitched_metrics.get("total_return", 0.0), 4) if stitched_metrics else 0.0,
                "num_windows": len(results),
                "overall_wfe": round(overall_wfe, 4) if overall_wfe else 0.0,
                "avg_oos_annual_return": round(avg_oos_annual_return, 2) if avg_oos_annual_return else 0.0,
                "total_oos_trades": total_oos_trades
            }
        }
