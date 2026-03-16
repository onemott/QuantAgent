import itertools
import asyncio
import optuna
from concurrent.futures import ProcessPoolExecutor
from typing import Dict, Any, List, Optional
import pandas as pd
import numpy as np

# Global variable for worker process to store read-only data
_worker_df = None

def _init_worker(df_data: Dict[str, Any]):
    """
    Initializer for worker process.
    Reconstructs DataFrame once per worker to avoid repeated serialization.
    """
    global _worker_df
    # Reconstruct DF
    df = pd.DataFrame(df_data)
    # Ensure index is datetime
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)
    _worker_df = df

# Define worker function at module level for pickle compatibility
def _worker_run_strategy(
    strategy_type: str,
    params: Dict[str, Any],
    initial_capital: float,
    use_numba: bool
) -> Dict[str, Any]:
    # Lazy imports to avoid overhead in main process
    import pandas as pd
    from app.services.strategy_templates import build_signal_func
    from app.services.backtester.vectorized import VectorizedBacktester
    from app.services.backtester.event_driven import EventDrivenBacktester
    
    global _worker_df
    if _worker_df is None:
        # Fallback if initializer failed or not used (should not happen in correct usage)
        return {
            "params": params,
            "error": "Worker not initialized with data",
            "sharpe": -999.0
        }
    
    try:
        signal_func = build_signal_func(strategy_type, params)
        
        if use_numba:
            bt = EventDrivenBacktester(_worker_df, signal_func, initial_capital)
        else:
            bt = VectorizedBacktester(_worker_df, signal_func, initial_capital)
            
        res = bt.run()
        
        return {
            "params": params,
            "sharpe": res.get("sharpe_ratio", 0.0),
            "total_return": res.get("total_return", 0.0),
            "max_drawdown": res.get("max_drawdown", 0.0),
            "win_rate": res.get("win_rate", 0.0),
            "total_trades": res.get("total_trades", 0),
        }
    except Exception as e:
        return {
            "params": params,
            "error": str(e),
            "sharpe": -999.0
        }

def _worker_run_chunk(
    strategy_type: str,
    chunk_params: List[Dict[str, Any]],
    initial_capital: float,
    use_numba: bool
) -> List[Dict[str, Any]]:
    results = []
    for params in chunk_params:
        res = _worker_run_strategy(strategy_type, params, initial_capital, use_numba)
        results.append(res)
    return results

class GridOptimizer:
    def __init__(self, df: pd.DataFrame, strategy_type: str, initial_capital: float = 10000.0):
        self.df = df
        self.strategy_type = strategy_type
        self.initial_capital = initial_capital
        
        # Prepare data for serialization
        # Reset index to make it a column, convert to dict
        temp_df = df.reset_index()
        # Rename index column to 'timestamp' if it doesn't have a name or is 'index'
        if 'index' in temp_df.columns:
            temp_df.rename(columns={'index': 'timestamp'}, inplace=True)
        elif temp_df.columns[0] == 'Date': # Common name
             temp_df.rename(columns={'Date': 'timestamp'}, inplace=True)
             
        self.df_data = temp_df.to_dict(orient='list')

    async def optimize(self, param_ranges: Dict[str, List[Any]], max_workers: int = 4, use_numba: bool = False) -> List[Dict[str, Any]]:
        param_names = list(param_ranges.keys())
        param_values = [param_ranges[k] for k in param_names]
        combinations = list(itertools.product(*param_values))
        
        loop = asyncio.get_running_loop()
        
        # Limit max_workers
        max_workers = min(max_workers, 8)
        
        # Chunking strategy: divide work roughly equally among workers, but not too small
        total_combos = len(combinations)
        if total_combos == 0:
            return []
            
        # Target ~4 chunks per worker to allow load balancing if some are slower
        target_chunks = max_workers * 4
        chunk_size = max(1, total_combos // target_chunks)
        
        # Create param dicts
        all_params = [dict(zip(param_names, combo)) for combo in combinations]
        
        # Create chunks
        chunks = [all_params[i:i + chunk_size] for i in range(0, total_combos, chunk_size)]
        
        # Use initializer to pass data once per worker
        with ProcessPoolExecutor(max_workers=max_workers, initializer=_init_worker, initargs=(self.df_data,)) as pool:
            tasks = []
            for chunk in chunks:
                tasks.append(
                    loop.run_in_executor(
                        pool, 
                        _worker_run_chunk, 
                        self.strategy_type, 
                        chunk, 
                        self.initial_capital,
                        use_numba
                    )
                )
            
            # Gather results (list of lists)
            chunk_results = await asyncio.gather(*tasks)
            
        # Flatten results
        results = [item for sublist in chunk_results for item in sublist]
        
        # Filter errors
        valid_results = [r for r in results if "error" not in r]
            
        # Filter errors
        valid_results = [r for r in results if "error" not in r]
        
        # Sort by Sharpe
        valid_results.sort(key=lambda x: x['sharpe'], reverse=True)
        return valid_results

class OptunaOptimizer:
    def __init__(self, df: pd.DataFrame, strategy_type: str, initial_capital: float = 10000.0):
        self.df = df
        self.strategy_type = strategy_type
        self.initial_capital = initial_capital

    def optimize(self, n_trials: int = 50, use_numba: bool = False) -> Dict[str, Any]:
        # We need to import inside method or at top level.
        from app.services.strategy_templates import get_template, build_signal_func
        from app.services.backtester.vectorized import VectorizedBacktester
        from app.services.backtester.event_driven import EventDrivenBacktester
        
        template = get_template(self.strategy_type)
        
        def objective(trial):
            params = {}
            for p in template['params']:
                key = p['key']
                if p['type'] == 'int':
                    step = p.get('step', 1)
                    params[key] = trial.suggest_int(key, p['min'], p['max'], step=int(step))
                elif p['type'] == 'float':
                    step = p.get('step', None)
                    if step:
                        params[key] = trial.suggest_float(key, p['min'], p['max'], step=step)
                    else:
                         params[key] = trial.suggest_float(key, p['min'], p['max'])
            
            signal_func = build_signal_func(self.strategy_type, params)
            
            if use_numba:
                bt = EventDrivenBacktester(self.df, signal_func, self.initial_capital)
            else:
                bt = VectorizedBacktester(self.df, signal_func, self.initial_capital)
                
            res = bt.run()
            
            # Handle NaN Sharpe
            sharpe = res.get('sharpe_ratio', 0.0)
            if np.isnan(sharpe):
                sharpe = -999.0
            
            # Store other metrics
            trial.set_user_attr("total_return", res.get("total_return", 0.0))
            trial.set_user_attr("max_drawdown", res.get("max_drawdown", 0.0))
            trial.set_user_attr("win_rate", res.get("win_rate", 0.0))
            trial.set_user_attr("total_trades", res.get("total_trades", 0))
                
            return sharpe

        # Suppress Optuna logs
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        study = optuna.create_study(direction='maximize')
        study.optimize(objective, n_trials=n_trials)
        
        best_params = study.best_params
        best_value = study.best_value
        
        # Get all trials
        trials = []
        for t in study.trials:
            if t.state == optuna.trial.TrialState.COMPLETE:
                 trials.append({
                     "params": t.params,
                     "sharpe": t.value,
                     "trial_number": t.number,
                     "total_return": t.user_attrs.get("total_return", 0.0),
                     "max_drawdown": t.user_attrs.get("max_drawdown", 0.0),
                     "win_rate": t.user_attrs.get("win_rate", 0.0),
                     "total_trades": t.user_attrs.get("total_trades", 0),
                 })
        
        trials.sort(key=lambda x: x['sharpe'], reverse=True)
        
        return {
            "best_params": best_params,
            "best_sharpe": best_value,
            "results": trials
        }
