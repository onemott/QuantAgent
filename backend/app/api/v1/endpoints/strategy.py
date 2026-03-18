"""
Strategy Endpoints
Provides strategy templates, backtest execution, result history,
parameter grid optimization, and multi-symbol batch backtests.
"""

import asyncio
import itertools
import logging
from datetime import datetime, date
from typing import List, Optional, Dict, Any

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services.strategy_templates import get_all_templates_meta, build_signal_func, get_template
from app.services.binance_service import binance_service
from app.services.database import get_db
from app.models.db_models import BacktestResult, OptimizationResult
from app.services.backtester import GridOptimizer, OptunaOptimizer

logger = logging.getLogger(__name__)
router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Request / Response Models
# ─────────────────────────────────────────────────────────────────────────────

class BacktestRequest(BaseModel):
    strategy_type:   str             # "ma" | "rsi" | "boll"
    symbol:          str = "BTCUSDT"
    interval:        str = "1d"      # "1h" | "4h" | "1d"
    limit:           int = 500       # number of candles to fetch
    initial_capital: float = 10000.0
    params:          Dict[str, Any] = {}


class TradeRecord(BaseModel):
    entry_time:   str
    exit_time:    str
    entry_price:  float
    exit_price:   float
    quantity:     float
    pnl:          float
    pnl_pct:      float


class BacktestMetrics(BaseModel):
    total_return:    float
    annual_return:   float
    max_drawdown:    float
    sharpe_ratio:    float
    win_rate:        float
    profit_factor:   float
    total_trades:    int
    total_commission: float
    initial_capital: float
    final_capital:   float


class TradeMarker(BaseModel):
    time:  str    # ISO timestamp
    price: float
    side:  str    # "BUY" | "SELL"
    pnl:   Optional[float] = None


class BacktestResponse(BaseModel):
    id:            Optional[int]
    strategy_type: str
    symbol:        str
    interval:      str
    params:        Dict[str, Any]
    metrics:       BacktestMetrics
    equity_curve:  List[Dict[str, Any]]  # [{t: ISO-string, v: float}]
    baseline_curve: List[Dict[str, Any]] # [{t: ISO-string, v: float}] buy-and-hold
    markers:       List[TradeMarker]     # buy/sell markers on price chart
    trades:        List[TradeRecord]
    created_at:    str


# ─────────────────────────────────────────────────────────────────────────────
# Strategy Templates
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/templates")
async def get_templates():
    """Return all available strategy templates with parameter definitions."""
    return {"templates": get_all_templates_meta()}


# ─────────────────────────────────────────────────────────────────────────────
# Backtest Execution
# ─────────────────────────────────────────────────────────────────────────────

from app.services.backtester.event_driven import EventDrivenBacktester

# ... (existing imports)

@router.post("/backtest/run", response_model=BacktestResponse)
async def run_backtest(req: BacktestRequest):
    """
    Run a strategy backtest using real Binance historical data.
    Results are persisted to PostgreSQL for later retrieval.
    """
    # Validate strategy type
    try:
        signal_func = build_signal_func(req.strategy_type, req.params)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Risk control: limit candles for high-frequency intervals
    MAX_LIMITS = {"15m": 500, "1h": 1000, "4h": 2000, "1d": 2000, "1w": 2000, "1M": 2000}
    effective_limit = min(req.limit, MAX_LIMITS.get(req.interval, 1000))

    # Normalize symbol to ccxt format
    symbol_ccxt = _normalize_symbol(req.symbol)
    symbol_clean = req.symbol.upper()

    # Fetch historical OHLCV from Binance
    try:
        df = await binance_service.get_klines_dataframe(symbol_ccxt, req.interval, limit=effective_limit)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Failed to fetch market data: {e}")

    if df is None or len(df) < 50:
        raise HTTPException(status_code=400, detail="Not enough candle data to run backtest (need ≥50)")

    # Run backtest engine (EventDrivenBacktester with Numba)
    try:
        # Use EventDrivenBacktester for high performance
        backtester = EventDrivenBacktester(
            df=df,
            signal_func=signal_func,
            initial_capital=req.initial_capital,
        )
        result = backtester.run()
        
        # Convert result to API format
        # 1. Equity Curve: Convert list of floats to [{t: time, v: value}]
        equity_values = result["equity_curve"]
        # Downsample for frontend performance if too large
        step = max(1, len(equity_values) // 500)
        equity_curve = [
            {"t": str(df.index[i])[:19], "v": round(equity_values[i], 2)}
            for i in range(0, len(equity_values), step)
        ]
        
        # 2. Trades: Already in list of dicts, ensure keys match TradeRecord
        trades_list = result["trades"]
        
        # 3. Markers: Generate from trades
        markers = []
        for t in trades_list:
            # Buy marker (Entry for Long)
            markers.append({
                "time": t["entry_time"],
                "price": t["entry_price"],
                "side": "BUY",
                "pnl": None
            })
            # Sell marker (Exit for Long)
            markers.append({
                "time": t["exit_time"],
                "price": t["exit_price"],
                "side": "SELL",
                "pnl": t["pnl"]
            })
        # Sort markers by time
        markers.sort(key=lambda x: x["time"])

    except Exception as e:
        logger.error(f"Backtest engine error: {e}", exc_info=True)
        # Fallback to pure python engine if Numba fails
        logger.warning("Falling back to pure Python engine due to error.")
        try:
             result = _run_backtest_engine(
                df=df,
                signal_func=signal_func,
                initial_capital=req.initial_capital,
                symbol=symbol_clean,
                timeframe=req.interval,
            )
             equity_curve = result["equity_curve"]
             trades_list = result["trades"]
             markers = result["markers"]
        except Exception as e2:
             raise HTTPException(status_code=500, detail=f"Backtest engine error: {e2}")

    # Run buy-and-hold baseline for comparison
    try:
        # Baseline can also use EventDriven for consistency, or keep pure python for simplicity
        baseline_result = _run_backtest_engine(
            df=df,
            signal_func=_buy_and_hold_signal,
            initial_capital=req.initial_capital,
            symbol=symbol_clean,
            timeframe=req.interval,
        )
        baseline_curve = baseline_result["equity_curve"]
    except Exception:
        baseline_curve = []

    # Build response data
    metrics_dict = {
        "total_return":     result["total_return"],
        "annual_return":    result["annual_return"],
        "max_drawdown":     result["max_drawdown"],
        "sharpe_ratio":     result["sharpe_ratio"],
        "win_rate":         result["win_rate"],
        "profit_factor":    result["profit_factor"],
        "total_trades":     result["total_trades"],
        "total_commission": result.get("total_commission", 0.0),
        "initial_capital":  req.initial_capital,
        "final_capital":    result["final_capital"],
    }

    # Persist to PostgreSQL
    db_id = None
    try:
        async with get_db() as session:
            bt_row = BacktestResult(
                strategy_type=req.strategy_type,
                symbol=symbol_clean,
                interval=req.interval,
                params=req.params,
                metrics=metrics_dict,
                equity_curve=equity_curve[:2000],   # cap to 2000 points (match max candles)
                trades_summary=trades_list[:100],    # store up to 100 trades for mid-freq strategies
            )
            session.add(bt_row)
            await session.flush()
            db_id = bt_row.id
    except Exception as e:
        logger.warning(f"Failed to persist backtest result: {e}")

    return BacktestResponse(
        id=db_id,
        strategy_type=req.strategy_type,
        symbol=symbol_clean,
        interval=req.interval,
        params=req.params,
        metrics=BacktestMetrics(**metrics_dict),
        equity_curve=equity_curve,
        baseline_curve=baseline_curve,
        markers=[TradeMarker(**m) for m in markers],
        trades=[TradeRecord(**t) for t in trades_list],
        created_at=datetime.utcnow().isoformat(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Backtest History
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/backtest/history")
async def get_backtest_history(
    strategy_type: Optional[str] = Query(None),
    symbol:        Optional[str] = Query(None),
    limit:         int = Query(20, ge=1, le=100),
):
    """Return previously saved backtest results (newest first)."""
    from sqlalchemy import select
    async with get_db() as session:
        stmt = (
            select(BacktestResult)
            .order_by(BacktestResult.created_at.desc())
            .limit(limit)
        )
        if strategy_type:
            stmt = stmt.where(BacktestResult.strategy_type == strategy_type)
        if symbol:
            stmt = stmt.where(BacktestResult.symbol == symbol.upper())
        result = await session.execute(stmt)
        rows = result.scalars().all()

    history = []
    for row in rows:
        # Reconstruct full backtest result from DB fields
        equity_curve = row.equity_curve if row.equity_curve else []
        trades_summary = row.trades_summary if row.trades_summary else []
        
        history.append({
            "id":             row.id,
            "strategy_type":  row.strategy_type,
            "symbol":         row.symbol,
            "interval":       row.interval,
            "params":         row.params,
            "metrics":        row.metrics,
            "equity_curve":   equity_curve,
            "baseline_curve": [],  # Not stored in DB, will be empty
            "markers":        [],   # Not stored in DB, will be empty
            "trades":         trades_summary,
            "created_at":     row.created_at.isoformat() if row.created_at else None,
        })
    return {"history": history, "total": len(history)}


# ─────────────────────────────────────────────────────────────────────────────
# Internal Backtest Engine
# ─────────────────────────────────────────────────────────────────────────────

def _run_backtest_engine(
    df: pd.DataFrame,
    signal_func,
    initial_capital: float,
    symbol: str,
    timeframe: str,
    commission: float = 0.001,
) -> Dict[str, Any]:
    """
    Pure-Python backtest engine (no external dependency).
    Returns dict with metrics, equity_curve, trades.
    """
    import numpy as np

    import inspect
    signals = signal_func(df)
    if inspect.isawaitable(signals):
        # We need to run it synchronously
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # This should not happen in _run_backtest_engine if called correctly, 
                # but let's be safe.
                import nest_asyncio
                nest_asyncio.apply()
            signals = loop.run_until_complete(signals)
        except Exception:
            signals = asyncio.run(signals)
    
    capital = initial_capital
    position = 0.0
    entry_price = 0.0
    entry_time = None
    trades = []
    markers = []   # buy/sell markers
    equity_list = []
    total_commission = 0.0

    prices = df["close"]
    times  = df.index

    for i in range(len(df)):
        price  = float(prices.iloc[i])
        signal = int(signals.iloc[i]) if i < len(signals) else 0
        current_time = times[i]

        current_equity = capital + position * price
        equity_list.append(current_equity)

        if signal == 1 and position == 0 and capital > 0:
            fee = capital * commission
            invest = capital - fee
            position = invest / price
            entry_price = price
            entry_time = current_time
            total_commission += fee
            capital = 0.0
            markers.append({
                "time":  str(current_time)[:19],
                "price": round(price, 6),
                "side":  "BUY",
                "pnl":   None,
            })

        elif signal == -1 and position > 0:
            gross = position * price
            fee = gross * commission
            net = gross - fee
            total_commission += fee

            pnl = net - (entry_price * position * (1 + commission))
            pnl_pct = (price / entry_price - 1) * 100 - commission * 200

            trades.append({
                "entry_time":  str(entry_time)[:19],
                "exit_time":   str(current_time)[:19],
                "entry_price": round(entry_price, 6),
                "exit_price":  round(price, 6),
                "quantity":    round(position, 8),
                "pnl":         round(pnl, 4),
                "pnl_pct":     round(pnl_pct, 4),
            })
            markers.append({
                "time":  str(current_time)[:19],
                "price": round(price, 6),
                "side":  "SELL",
                "pnl":   round(pnl, 4),
            })
            capital = net
            position = 0.0
            entry_price = 0.0
            entry_time = None

    # Force-close at last bar
    if position > 0:
        price = float(prices.iloc[-1])
        fee = position * price * commission
        net = position * price - fee
        total_commission += fee
        pnl = net - (entry_price * position * (1 + commission))
        pnl_pct = (price / entry_price - 1) * 100 - commission * 200
        trades.append({
            "entry_time":  str(entry_time)[:19],
            "exit_time":   str(times[-1])[:19],
            "entry_price": round(entry_price, 6),
            "exit_price":  round(price, 6),
            "quantity":    round(position, 8),
            "pnl":         round(pnl, 4),
            "pnl_pct":     round(pnl_pct, 4),
        })
        markers.append({
            "time":  str(times[-1])[:19],
            "price": round(price, 6),
            "side":  "SELL",
            "pnl":   round(pnl, 4),
        })
        capital = net
        position = 0.0

    equity_series = pd.Series(equity_list, index=times)
    final_capital = capital

    # Metrics
    total_return = (final_capital / initial_capital - 1) * 100
    n_days = (times[-1] - times[0]).days
    annual_return = (
        ((1 + total_return / 100) ** (365 / n_days) - 1) * 100 if n_days > 0 else 0.0
    )

    rolling_max  = equity_series.cummax()
    drawdown     = (equity_series - rolling_max) / rolling_max
    max_drawdown = abs(float(drawdown.min())) * 100

    daily_ret     = equity_series.pct_change().dropna()
    risk_free_d   = 0.02 / 365
    excess_ret    = daily_ret - risk_free_d
    sharpe = (
        float((excess_ret.mean() / daily_ret.std()) * np.sqrt(365))
        if daily_ret.std() > 0 else 0.0
    )

    n_trades = len(trades)
    if n_trades > 0:
        winning = [t for t in trades if t["pnl"] > 0]
        losing  = [t for t in trades if t["pnl"] < 0]
        win_rate = len(winning) / n_trades * 100
        avg_win  = float(np.mean([t["pnl"] for t in winning])) if winning else 0.0
        avg_loss = abs(float(np.mean([t["pnl"] for t in losing]))) if losing else 0.0
        profit_factor = avg_win / avg_loss if avg_loss > 0 else float("inf")
    else:
        win_rate = profit_factor = 0.0

    # Equity curve: sample to max 500 points to keep response small
    step = max(1, len(equity_series) // 500)
    sampled = equity_series.iloc[::step]
    equity_curve = [
        {"t": str(idx)[:19], "v": round(val, 2)}
        for idx, val in sampled.items()
    ]

    return {
        "total_return":    round(total_return, 4),
        "annual_return":   round(annual_return, 4),
        "max_drawdown":    round(max_drawdown, 4),
        "sharpe_ratio":    round(sharpe, 4),
        "win_rate":        round(win_rate, 4),
        "profit_factor":   round(min(profit_factor, 999.0), 4),
        "total_trades":    n_trades,
        "total_commission": round(total_commission, 4),
        "final_capital":   round(final_capital, 4),
        "equity_curve":    equity_curve,
        "markers":         markers,
        "trades":          trades,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Buy-and-Hold baseline signal
# ─────────────────────────────────────────────────────────────────────────────

def _buy_and_hold_signal(df):
    """Buy first candle, sell last candle — market benchmark."""
    import pandas as pd
    signals = pd.Series(0, index=df.index)
    signals.iloc[0]  = 1
    signals.iloc[-1] = -1
    return signals

def _normalize_symbol(symbol: str) -> str:
    symbol = symbol.upper()
    if "/" not in symbol:
        for quote in ("USDT", "BTC", "ETH", "BNB", "BUSD"):
            if symbol.endswith(quote):
                base = symbol[: -len(quote)]
                return f"{base}/{quote}"
    return symbol


# ─────────────────────────────────────────────────────────────────────────────
# Parameter Grid Optimization
# ─────────────────────────────────────────────────────────────────────────────

class OptimizeRequest(BaseModel):
    strategy_type:   str
    symbol:          str = "BTCUSDT"
    interval:        str = "1d"
    limit:           int = 500
    initial_capital: float = 10000.0
    param_ranges:    Dict[str, List[Any]] = {}
    max_combos:      int = 100
    algorithm:       str = "grid" # "grid" | "optuna"
    n_trials:        int = 50     # For Optuna
    use_numba:       bool = False # Experimental


class OptimizeResponse(BaseModel):
    strategy_type: str
    symbol:        str
    interval:      str
    best_params:   Dict[str, Any]
    best_sharpe:   float
    best_return:   float
    total_combos:  int
    results:       List[Dict[str, Any]]
    saved_id:      Optional[int] = None


@router.post("/optimize", response_model=OptimizeResponse)
async def optimize_strategy(req: OptimizeRequest):
    """
    Run parameter optimization for a strategy.
    Supports Grid Search (default) and Optuna (Bayesian Optimization).
    """
    try:
        get_template(req.strategy_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Validate combos for Grid Search
    if req.algorithm == "grid":
        param_names  = list(req.param_ranges.keys()) if req.param_ranges else []
        param_values = [req.param_ranges[k] for k in param_names]
        if not param_names:
            total_combos = 1
        else:
            total_combos = 1
            for v in param_values:
                total_combos *= len(v)
                
        if total_combos > req.max_combos:
            raise HTTPException(
                status_code=400,
                detail=f"参数组合总数 {total_combos} 超过安全上限 {req.max_combos}"
            )
    else:
        total_combos = req.n_trials

    symbol_ccxt  = _normalize_symbol(req.symbol)
    symbol_clean = req.symbol.upper()
    MAX_LIMITS   = {"15m": 500, "1h": 1000, "4h": 2000, "1d": 2000, "1w": 2000, "1M": 2000}
    effective_limit = min(req.limit, MAX_LIMITS.get(req.interval, 1000))

    try:
        df = await binance_service.get_klines_dataframe(symbol_ccxt, req.interval, limit=effective_limit)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Failed to fetch market data: {e}")

    if df is None or len(df) < 50:
        raise HTTPException(status_code=400, detail="K线数据不足（至少需要 50 根）")

    # Run Optimization
    if req.algorithm == "optuna":
        optimizer = OptunaOptimizer(df, req.strategy_type, req.initial_capital)
        # Optuna runs in a thread to avoid blocking event loop
        result = await asyncio.to_thread(optimizer.optimize, n_trials=req.n_trials, use_numba=req.use_numba)
        
        valid_results = result["results"]
        best_params = result["best_params"]
        best_sharpe = result["best_sharpe"]
        
        # Find best result details
        best_return = 0.0
        if valid_results:
            best_res = valid_results[0] # Sorted by sharpe
            best_return = best_res.get("total_return", 0.0)
            
    else: # grid
        optimizer = GridOptimizer(df, req.strategy_type, req.initial_capital)
        valid_results = await optimizer.optimize(req.param_ranges, use_numba=req.use_numba)
        
        if valid_results:
            best = valid_results[0]
            best_params = best["params"]
            best_sharpe = best["sharpe"]
            best_return = best["total_return"]
        else:
            best_params = {}
            best_sharpe = 0.0
            best_return = 0.0

    params_grid = valid_results[:50]

    saved_id = None
    try:
        async with get_db() as session:
            row = OptimizationResult(
                strategy_type=req.strategy_type,
                symbol=symbol_clean,
                interval=req.interval,
                params_grid=params_grid,
                best_params=best_params,
                best_sharpe=best_sharpe,
                best_return=best_return,
                total_combos=total_combos,
            )
            session.add(row)
            await session.flush()
            saved_id = row.id
    except Exception as e:
        logger.warning(f"Failed to persist optimization result: {e}")

    return OptimizeResponse(
        strategy_type=req.strategy_type,
        symbol=symbol_clean,
        interval=req.interval,
        best_params=best_params,
        best_sharpe=round(best_sharpe, 4),
        best_return=round(best_return, 4),
        total_combos=total_combos,
        results=valid_results[:50],
        saved_id=saved_id,
    )


@router.get("/optimize/history")
async def get_optimization_history(
    strategy_type: Optional[str] = Query(None),
    symbol:        Optional[str] = Query(None),
    limit:         int = Query(20, ge=1, le=100),
):
    """Return previously saved optimization results (newest first)."""
    from sqlalchemy import select as sa_select
    async with get_db() as session:
        stmt = (
            sa_select(OptimizationResult)
            .order_by(OptimizationResult.created_at.desc())
            .limit(limit)
        )
        if strategy_type:
            stmt = stmt.where(OptimizationResult.strategy_type == strategy_type)
        if symbol:
            stmt = stmt.where(OptimizationResult.symbol == symbol.upper())
        result = await session.execute(stmt)
        rows = result.scalars().all()

    return {
        "history": [
            {
                "id":            row.id,
                "strategy_type": row.strategy_type,
                "symbol":        row.symbol,
                "interval":      row.interval,
                "best_params":   row.best_params,
                "best_sharpe":   row.best_sharpe,
                "best_return":   row.best_return,
                "total_combos":  row.total_combos,
                "created_at":    row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
        "total": len(rows),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Multi-Symbol Batch Backtest
# ─────────────────────────────────────────────────────────────────────────────

class BatchBacktestRequest(BaseModel):
    strategy_type:   str
    symbols:         List[str] = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
    interval:        str = "1d"
    limit:           int = 500
    initial_capital: float = 10000.0
    params:          Dict[str, Any] = {}


class BatchBacktestItem(BaseModel):
    symbol:        str
    total_return:  float
    annual_return: float
    sharpe_ratio:  float
    max_drawdown:  float
    win_rate:      float
    total_trades:  int
    error:         Optional[str] = None


class BatchBacktestResponse(BaseModel):
    strategy_type: str
    interval:      str
    params:        Dict[str, Any]
    results:       List[BatchBacktestItem]
    total_symbols: int
    success_count: int


@router.post("/backtest/batch", response_model=BatchBacktestResponse)
async def batch_backtest(req: BatchBacktestRequest):
    """
    Run the same strategy across multiple symbols concurrently.
    Returns a leaderboard ranked by total return.
    """
    if len(req.symbols) > 20:
        raise HTTPException(status_code=400, detail="最多同时回测 20 个标的")

    try:
        build_signal_func(req.strategy_type, req.params)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    MAX_LIMITS = {"15m": 500, "1h": 1000, "4h": 2000, "1d": 2000, "1w": 2000, "1M": 2000}
    effective_limit = min(req.limit, MAX_LIMITS.get(req.interval, 1000))

    async def _run_one(symbol: str) -> BatchBacktestItem:
        try:
            symbol_ccxt  = _normalize_symbol(symbol)
            symbol_clean = symbol.upper()
            df = await binance_service.get_klines_dataframe(
                symbol_ccxt, req.interval, limit=effective_limit
            )
            if df is None or len(df) < 50:
                return BatchBacktestItem(symbol=symbol_clean, total_return=0, annual_return=0,
                                         sharpe_ratio=0, max_drawdown=0, win_rate=0,
                                         total_trades=0, error="数据不足")
            sig_func = build_signal_func(req.strategy_type, req.params)
            result   = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: _run_backtest_engine(
                    df=df, signal_func=sig_func, initial_capital=req.initial_capital,
                    symbol=symbol_clean, timeframe=req.interval,
                )
            )
            return BatchBacktestItem(
                symbol=symbol_clean,
                total_return=result["total_return"],
                annual_return=result["annual_return"],
                sharpe_ratio=result["sharpe_ratio"],
                max_drawdown=result["max_drawdown"],
                win_rate=result["win_rate"],
                total_trades=result["total_trades"],
            )
        except Exception as e:
            return BatchBacktestItem(
                symbol=symbol.upper(), total_return=0, annual_return=0,
                sharpe_ratio=0, max_drawdown=0, win_rate=0,
                total_trades=0, error=str(e)[:120],
            )

    items       = await asyncio.gather(*[_run_one(s) for s in req.symbols])
    items_list  = sorted(items, key=lambda x: x.total_return if not x.error else -9999, reverse=True)
    success_cnt = sum(1 for i in items_list if not i.error)

    return BatchBacktestResponse(
        strategy_type=req.strategy_type,
        interval=req.interval,
        params=req.params,
        results=items_list,
        total_symbols=len(req.symbols),
        success_count=success_cnt,
    )
