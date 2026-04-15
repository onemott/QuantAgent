import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.services.backtester.optimizer import OptunaOptimizer
from app.services.backtester.annualization import annualize_sharpe, infer_annualization_factor, validate_datetime_index
from app.services.walk_forward.window_manager import WindowManager
from app.services.walk_forward.stability_analyzer import StabilityAnalyzer
from app.services.strategy_templates import build_signal_func
from app.services.backtester.vectorized import VectorizedBacktester
from app.services.backtester.signal_resolution import resolve_signal_output


logger = logging.getLogger(__name__)


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
        visible_index: pd.Index,
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
            visible_returns_series = WalkForwardOptimizer._build_returns_series(visible_returns, visible_index)
            annual_return = WalkForwardOptimizer._annualized_return_decimal(
                visible_returns_series,
                annualization_factor,
                context="visible_oos",
            )
            sharpe_ratio = annualize_sharpe(
                visible_returns_series,
                WalkForwardOptimizer._resolve_window_annualization_factor(visible_returns_series.index, annualization_factor),
            )
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
            # WFA 服务层统一使用小数口径，例如 0.12 表示 12%。
            "annual_return": annual_return,
            "max_drawdown": max_drawdown,
            "sharpe_ratio": sharpe_ratio,
            "total_trades": total_trades,
            "final_capital": final_capital,
            "final_position": raw_performance.get("final_position", 0.0),
            "equity_curve": visible_equity,
            "returns": visible_returns,
        }

    @staticmethod
    def _build_returns_series(returns: List[float], index: pd.Index | None = None) -> pd.Series:
        """构造收益率序列，优先保留时间索引以便按窗口动态推导年化因子。"""
        if not returns:
            return pd.Series(dtype=float)

        if index is not None and len(index) == len(returns):
            return pd.Series(returns, index=index, dtype=float)

        if index is not None and len(index) != len(returns):
            logger.warning(
                "Return series length mismatch; falling back to positional index. "
                "returns=%s, index=%s",
                len(returns),
                len(index),
            )

        return pd.Series(returns, dtype=float)

    @staticmethod
    def _resolve_window_annualization_factor(index: pd.Index, fallback_annualization_factor: int) -> int:
        """
        基于窗口自身索引推导年化因子。

        这样在窗口被截断、存在停牌/缺口或样本频率与全局数据不完全一致时，
        不会错误复用整段数据的固定年化因子。
        """
        if isinstance(index, pd.DatetimeIndex) and len(index) > 1:
            try:
                return max(infer_annualization_factor(index), 1)
            except ValueError:
                logger.warning(
                    "Failed to infer annualization factor from window index; using fallback=%s.",
                    fallback_annualization_factor,
                )

        return max(fallback_annualization_factor, 1)

    @staticmethod
    def _annualized_return_decimal(
        returns: pd.Series,
        fallback_annualization_factor: int,
        context: str,
    ) -> float:
        """
        统一按小数口径计算 WFA 年化收益率。

        示例：返回 `0.25` 表示 25%，由展示层决定是否乘以100。
        """
        sanitized_returns = pd.Series(returns, dtype=float).dropna()
        if sanitized_returns.empty:
            return 0.0

        annualization_factor = WalkForwardOptimizer._resolve_window_annualization_factor(
            sanitized_returns.index,
            fallback_annualization_factor,
        )
        annual_return = StabilityAnalyzer._annualized_return(sanitized_returns, annualization_factor)

        if annual_return > 5.0:
            logger.warning(
                "Extreme annualized return detected in %s. "
                "annual_return=%.6f, periods=%s, annualization_factor=%s",
                context,
                annual_return,
                len(sanitized_returns),
                annualization_factor,
            )

        return annual_return

    @staticmethod
    def _validate_run_configuration(
        is_days: int,
        oos_days: int,
        step_days: Optional[int],
        n_trials: int,
        embargo_days: int,
    ) -> None:
        """Validate runtime configuration before generating windows."""
        if is_days <= 0:
            raise ValueError("is_days must be > 0")
        if oos_days <= 0:
            raise ValueError("oos_days must be > 0")
        if step_days is not None and step_days <= 0:
            raise ValueError("step_days must be > 0")
        if n_trials <= 0:
            raise ValueError("n_trials must be > 0")
        if embargo_days < 0:
            raise ValueError("embargo_days must be >= 0")

    @staticmethod
    def _resolve_evaluation_slice(
        test_start_idx: int,
        test_end_idx: int,
    ) -> Tuple[int, int]:
        """
        Build a full OOS evaluation slice.

        We include one prior bar when possible so the first visible OOS return uses
        the correct lagged position without relying on external state.
        """
        backtest_start_idx = max(test_start_idx - 1, 0)
        visible_offset = test_start_idx - backtest_start_idx
        return backtest_start_idx, visible_offset

    @staticmethod
    def _resolve_stitched_slice(
        test_start_idx: int,
        test_end_idx: int,
        last_stitched_end_idx: Optional[int],
    ) -> Optional[Tuple[int, int]]:
        """
        Build the incremental slice used for stitched OOS equity.

        This avoids double-counting when OOS windows overlap (`step_days < oos_days`).
        """
        unseen_start_idx = test_start_idx
        if last_stitched_end_idx is not None:
            unseen_start_idx = max(test_start_idx, last_stitched_end_idx + 1)

        if unseen_start_idx > test_end_idx:
            return None

        backtest_start_idx = max(unseen_start_idx - 1, 0)
        visible_offset = unseen_start_idx - backtest_start_idx
        return backtest_start_idx, visible_offset

    @staticmethod
    def _coerce_signal_series(signals: Any, index: pd.Index) -> pd.Series:
        """Normalize strategy signals into an indexed float Series."""
        if isinstance(signals, pd.Series):
            return signals.reindex(index).fillna(0.0).astype(float)
        return pd.Series(signals, index=index, dtype=float).fillna(0.0)

    @staticmethod
    def _infer_initial_position(
        signals: pd.Series,
        start_idx: int,
        fallback_position: float = 0.0,
    ) -> float:
        """
        Infer the position state immediately before a sliced backtest starts.

        This preserves the original sparse-signal semantics when the OOS slice
        does not begin at the start of the full signal history.
        """
        if start_idx <= 0 or signals.empty:
            return float(fallback_position)

        historical_signals = pd.Series(signals.iloc[:start_idx], dtype=float)
        if historical_signals.empty:
            return float(fallback_position)

        position = historical_signals.replace(0, np.nan).ffill()
        if pd.isna(position.iloc[0]):
            position.iloc[0] = fallback_position
            position = position.ffill()
        position = position.fillna(0.0).clip(lower=0.0)
        return float(position.iloc[-1]) if not position.empty else float(fallback_position)

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
            self._validate_run_configuration(is_days, oos_days, step_days, n_trials, embargo_days)
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
        last_stitched_end_idx: Optional[int] = None
        
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

            is_annualization_factor = self._resolve_window_annualization_factor(is_df.index, annualization_factor)
            oos_annualization_factor = self._resolve_window_annualization_factor(oos_df.index, annualization_factor)
                 
            signal_func = build_signal_func(self.strategy_type, best_params)
              
            full_df = self.df.loc[:test_end]
            full_oos_signals = self._coerce_signal_series(
                resolve_signal_output(signal_func(full_df)),
                full_df.index,
            )

            test_start_idx = self.df.index.get_indexer([test_start])[0]
            test_end_idx = self.df.index.get_indexer([test_end])[0]
            window_backtest_start_idx, window_visible_offset = self._resolve_evaluation_slice(
                test_start_idx,
                test_end_idx,
            )
            oos_df_bt = self.df.iloc[window_backtest_start_idx:test_end_idx + 1]
            window_initial_position = self._infer_initial_position(
                full_oos_signals,
                window_backtest_start_idx,
            )
             
            def oos_signal_wrapper(df_for_bt: pd.DataFrame) -> pd.Series:
                return full_oos_signals.loc[df_for_bt.index]

            # Evaluate the full OOS window independently for WFE and per-window metrics.
            bt = VectorizedBacktester(
                oos_df_bt, 
                oos_signal_wrapper, 
                self.initial_capital,
                initial_position=window_initial_position,
                annualization_factor=oos_annualization_factor
            )
            raw_oos_perf = await asyncio.to_thread(bt.run)
            oos_dates = oos_df_bt.index.tolist()[window_visible_offset:]
            oos_perf = self._build_visible_oos_performance(
                raw_oos_perf,
                window_visible_offset,
                self.initial_capital,
                pd.Index(oos_dates),
                oos_annualization_factor,
            )

            oos_equity = oos_perf.get("equity_curve", [])
            oos_returns_list = oos_perf.get("returns", [])

            stitched_slice = self._resolve_stitched_slice(
                test_start_idx,
                test_end_idx,
                last_stitched_end_idx,
            )
            if stitched_slice is not None:
                stitched_backtest_start_idx, stitched_visible_offset = stitched_slice
                stitched_df_bt = self.df.iloc[stitched_backtest_start_idx:test_end_idx + 1]
                stitched_dates_segment = stitched_df_bt.index.tolist()[stitched_visible_offset:]

                stitched_bt = VectorizedBacktester(
                    stitched_df_bt,
                    oos_signal_wrapper,
                    current_capital,
                    initial_position=current_position,
                    annualization_factor=oos_annualization_factor,
                )
                raw_stitched_perf = await asyncio.to_thread(stitched_bt.run)
                stitched_segment_perf = self._build_visible_oos_performance(
                    raw_stitched_perf,
                    stitched_visible_offset,
                    current_capital,
                    pd.Index(stitched_dates_segment),
                    oos_annualization_factor,
                )
                current_position = raw_stitched_perf.get("final_position", current_position)

                stitched_segment_equity = stitched_segment_perf.get("equity_curve", [])
                if stitched_segment_equity:
                    stitched_equity_curve.extend(stitched_segment_equity)
                    stitched_dates.extend(stitched_dates_segment)
                    current_capital = stitched_segment_equity[-1]
                    last_stitched_end_idx = test_end_idx
                 
            # For StabilityAnalyzer, we need returns as pd.Series
            oos_returns = self._build_returns_series(oos_returns_list, pd.Index(oos_dates))
            
            # IS returns
            full_is_df = self.df.loc[:train_end]
            full_is_signals = self._coerce_signal_series(
                resolve_signal_output(signal_func(full_is_df)),
                full_is_df.index,
            )

            def is_signal_wrapper(df_for_bt: pd.DataFrame) -> pd.Series:
                return full_is_signals.loc[df_for_bt.index]

            is_bt = VectorizedBacktester(
                is_df,
                is_signal_wrapper,
                self.initial_capital,
                annualization_factor=is_annualization_factor
            )
            is_perf = await asyncio.to_thread(is_bt.run)
            is_returns_list = is_perf.get("returns", [])
            is_returns = self._build_returns_series(is_returns_list, is_df.index)

             
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
                "oos_annual_return": oos_perf.get("annual_return", 0.0),
                "oos_drawdown": oos_perf.get("max_drawdown", 0.0),
                "oos_trades": oos_perf.get("total_trades", 0),
                "metric_types": {
                    "is_sharpe": "decimal",
                    "is_return": "percentage",
                    "oos_sharpe": "decimal",
                    "oos_return": "percentage",
                    "oos_annual_return": "decimal",
                    "oos_drawdown": "percentage",
                    "oos_trades": "absolute_value",
                    "wfe": "decimal",
                    "param_stability": "decimal",
                },
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
        window_param_stability = stability_report.get("window_parameter_stability", [])
        for i, res in enumerate(results):
            if i < len(wfe_per_window):
                res['wfe'] = wfe_per_window[i]
            if i < len(window_param_stability):
                res["param_stability"] = float(window_param_stability[i])
                 
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
            stitched_returns = self._build_returns_series(all_oos_returns_list, pd.Index(stitched_dates))
            annual_return = self._annualized_return_decimal(
                stitched_returns,
                annualization_factor,
                context="stitched_oos",
            )
            sharpe_ratio = annualize_sharpe(
                stitched_returns,
                self._resolve_window_annualization_factor(stitched_returns.index, annualization_factor),
            )
             
            stitched_metrics = {
                "total_return": total_return,
                "annual_return": annual_return,
                "max_drawdown": max_drawdown,
                "sharpe_ratio": sharpe_ratio,
                "final_capital": stitched_equity_curve[-1],
                "equity_curve": stitched_equity_curve,
                "dates": [d.isoformat() for d in stitched_dates],
                "metric_types": {
                    "total_return": "percentage",
                    "annual_return": "decimal",
                    "max_drawdown": "percentage",
                    "sharpe_ratio": "decimal",
                    "final_capital": "absolute_value",
                },
            }

        # Handle stability_report numpy types (like float64) which are not JSON serializable
        # We can just return it, fastapi jsonable_encoder handles standard python types, we might need to convert
        # parameter_stability_scores
        param_scores = stability_report.get("parameter_stability_scores", {})
        for k, v in param_scores.items():
            if isinstance(v, (np.float64, np.float32)):
                param_scores[k] = float(v)
        stability_report["parameter_stability_scores"] = param_scores
        stability_report["window_parameter_stability"] = [
            float(value) if isinstance(value, (np.float64, np.float32)) else value
            for value in stability_report.get("window_parameter_stability", [])
        ]

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
                "avg_oos_annual_return": round(avg_oos_annual_return, 4) if avg_oos_annual_return else 0.0,
                "total_oos_trades": total_oos_trades,
                "metric_types": {
                    "avg_oos_sharpe": "decimal",
                    "total_oos_return": "percentage",
                    "num_windows": "absolute_value",
                    "overall_wfe": "decimal",
                    "avg_oos_annual_return": "decimal",
                    "total_oos_trades": "absolute_value",
                },
            }
        }
