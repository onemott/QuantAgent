"""
Analytics Endpoints
Provides performance metrics, equity curve, trade pairs, and position analysis.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.services.attribution_service import attribution_service
from app.services.performance_service import performance_service
from app.services.trade_pair_service import trade_pair_service
from app.services.position_analysis_service import position_analysis_service
from app.services.paper_trading_service import paper_trading_service
from app.services.database import get_db, redis_get, redis_set
from app.models.db_models import EquitySnapshot

from sqlalchemy import select

router = APIRouter()

REDIS_PERF_KEY = "analytics:performance:{period}"
REDIS_EQUITY_KEY = "analytics:equity:{period}"
REDIS_PORTFOLIO_KEY = "analytics:portfolio"
CACHE_TTL = 30  # 30 seconds cache


# ─────────────────────────────────────────────────────────────────────────────
# Performance Metrics
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/performance")
async def get_performance_metrics(
    period: str = Query("all_time", pattern="^(daily|today|weekly|monthly|all_time)$")
):
    """Get aggregated performance metrics for a given period."""
    cache_key = REDIS_PERF_KEY.format(period=period)
    
    cached = await redis_get(cache_key)
    if cached is not None:
        return cached
    
    now = datetime.now(timezone.utc)

    if period in ("daily", "today"):
        start = now - timedelta(days=1)
    elif period == "weekly":
        start = now - timedelta(weeks=1)
    elif period == "monthly":
        start = now - timedelta(days=30)
    else:
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)

    try:
        metrics = await performance_service.calculate_metrics(
            start, now, Decimal("100000")
        )
        await redis_set(cache_key, metrics, ttl=CACHE_TTL)
        return metrics
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to calculate metrics: {e}")


@router.get("/attribution")
async def get_attribution(
    period: str = Query("all_time", pattern="^(daily|today|weekly|monthly|all_time)$")
):
    """Get profit attribution by strategy."""
    now = datetime.now(timezone.utc)
    if period in ("daily", "today"):
        start = now - timedelta(days=1)
    elif period == "weekly":
        start = now - timedelta(weeks=1)
    elif period == "monthly":
        start = now - timedelta(days=30)
    else:
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)

    try:
        attribution = await performance_service.get_attribution(start, now)
        return {"attribution": attribution}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get attribution: {e}")


@router.get("/attribution/strategy/{strategy_id}")
async def get_strategy_attribution(
    strategy_id: str,
    symbol: str = Query("BTCUSDT"),
    days: int = Query(7, ge=1, le=30),
    base_mode: str = Query("backtest"),
    compare_mode: Optional[str] = Query(None),
    replay_session_id: Optional[str] = Query(None)
):
    """Get detailed attribution analysis for a specific strategy."""
    try:
        report = await attribution_service.get_strategy_attribution(
            strategy_id=strategy_id,
            symbol=symbol,
            days=days,
            base_mode=base_mode,
            compare_mode=compare_mode,
            replay_session_id=replay_session_id
        )
        return report
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get attribution report: {e}")


@router.get("/strategy-comparison")
async def get_strategy_comparison():
    """Compare paper trading performance vs latest backtest results."""
    from app.models.db_models import BacktestResult, TradePair
    from sqlalchemy import func as sa_func

    async with get_db() as session:
        # 1. Get paper trading metrics per strategy
        stmt = (
            select(
                TradePair.strategy_id,
                sa_func.sum(TradePair.pnl).label("total_pnl"),
                sa_func.count(TradePair.id).label("trade_count"),
                sa_func.avg(TradePair.pnl_pct).label("win_rate") # Simplification for demo
            )
            .where(TradePair.status == "CLOSED")
            .group_by(TradePair.strategy_id)
        )
        paper_res = await session.execute(stmt)
        paper_data = {row.strategy_id: row for row in paper_res.all() if row.strategy_id}

        # 2. Get latest backtest results for these strategies
        # We'll map auto_trend_ma -> ma, auto_reversion_rsi -> rsi, etc.
        strategy_map = {
            "auto_trend_ma": "ma",
            "auto_reversion_rsi": "rsi",
            "auto_volatility_boll": "boll"
        }
        
        comparison = []
        for auto_id, template_id in strategy_map.items():
            # Find latest backtest for this template
            bt_stmt = (
                select(BacktestResult)
                .where(BacktestResult.strategy_type == template_id)
                .order_by(BacktestResult.created_at.desc())
                .limit(1)
            )
            bt_res = await session.execute(bt_stmt)
            bt_row = bt_res.scalar_one_or_none()
            
            paper_row = paper_data.get(auto_id)
            
            comparison.append({
                "strategy_id": auto_id,
                "strategy_name": template_id.upper(),
                "paper": {
                    "total_pnl": float(paper_row.total_pnl or 0.0) if paper_row else 0.0,
                    "trade_count": int(paper_row.trade_count or 0) if paper_row else 0,
                },
                "backtest": {
                    "total_return": float((bt_row.metrics or {}).get("total_return", 0.0)) if bt_row else 0.0,
                    "win_rate": float((bt_row.metrics or {}).get("win_rate", 0.0)) if bt_row else 0.0,
                    "max_drawdown": float((bt_row.metrics or {}).get("max_drawdown", 0.0)) if bt_row else 0.0,
                } if bt_row else None
            })
            
        return {"comparison": comparison}


# ─────────────────────────────────────────────────────────────────────────────
# Equity Curve
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/equity-curve")
async def get_equity_curve(
    period: str = Query("all_time"),
    interval: str = Query("1h", pattern="^(1h|4h|1d)$"),
):
    """Get equity curve data points for charting."""
    cache_key = f"{REDIS_EQUITY_KEY.format(period=period)}:{interval}"
    
    cached = await redis_get(cache_key)
    if cached is not None:
        return cached
    
    now = datetime.now(timezone.utc)

    if period in ("daily", "today"):
        start = now - timedelta(days=1)
    elif period == "weekly":
        start = now - timedelta(weeks=1)
    elif period == "monthly":
        start = now - timedelta(days=30)
    else:
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)

    async with get_db() as session:
        result = await session.execute(
            select(EquitySnapshot)
            .where(EquitySnapshot.timestamp >= start)
            .where(EquitySnapshot.timestamp <= now)
            .order_by(EquitySnapshot.timestamp.asc())
        )
        snapshots = result.scalars().all()

    curve = []
    for s in snapshots:
        curve.append({
            "timestamp": s.timestamp.isoformat() if s.timestamp else None,
            "total_equity": float(s.total_equity),
            "cash_balance": float(s.cash_balance),
            "position_value": float(s.position_value) if s.position_value else 0,
            "daily_pnl": float(s.daily_pnl) if s.daily_pnl else 0,
            "daily_return": float(s.daily_return) if s.daily_return else 0,
            "drawdown": float(s.drawdown) if s.drawdown else 0,
        })

    # Apply interval downsampling if needed
    if interval == "4h" and len(curve) > 0:
        curve = curve[::4]  # Every 4th point
    elif interval == "1d" and len(curve) > 0:
        curve = curve[::24]  # Every 24th point

    return {"curve": curve, "total": len(curve)}


# ─────────────────────────────────────────────────────────────────────────────
# Trade Pairs
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/trade-pairs")
async def get_trade_pairs(
    status: Optional[str] = Query(None, pattern="^(OPEN|CLOSED)$"),
    symbol: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
):
    """Get trade pair list with optional filtering."""
    try:
        pairs = await trade_pair_service.get_trade_pairs(
            status=status, symbol=symbol, limit=limit
        )
        return {"pairs": pairs, "total": len(pairs)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get trade pairs: {e}")


@router.get("/trade-pairs/{pair_id}")
async def get_trade_pair_detail(pair_id: str):
    """Get detailed info for a single trade pair."""
    detail = await trade_pair_service.get_pair_detail(pair_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Trade pair {pair_id} not found")
    return detail


# ─────────────────────────────────────────────────────────────────────────────
# Position Analysis
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/positions/analysis")
async def get_positions_analysis():
    """Get portfolio-level position analysis with real-time prices."""
    try:
        # Get current positions
        positions_raw = await paper_trading_service.get_positions()
        if not positions_raw:
            return {
                "total_equity": 0,
                "cash": 0,
                "position_value": 0,
                "cash_pct": 100,
                "total_unrealized_pnl": 0,
                "asset_allocation": [],
                "exposure": {
                    "long": 0, "short": 0,
                    "net_exposure": 0, "gross_exposure": 0, "leverage": 0
                },
                "position_count": 0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        # Fetch current prices
        current_prices = {}
        for pos in positions_raw:
            symbol = pos["symbol"]
            try:
                from app.services.binance_service import binance_service
                symbol_ccxt = _normalize_symbol(symbol)
                ticker = await binance_service.get_ticker(symbol_ccxt)
                current_prices[symbol] = ticker.price
            except Exception:
                current_prices[symbol] = pos["avg_price"]

        portfolio = await position_analysis_service.get_portfolio_analytics(
            positions_raw, current_prices
        )
        return portfolio
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to analyze positions: {e}"
        )


@router.get("/positions/analysis/{symbol}")
async def get_position_analysis_detail(symbol: str):
    """Get detailed analysis for a specific position."""
    symbol = symbol.upper()
    try:
        # Get current price
        from app.services.binance_service import binance_service
        symbol_ccxt = _normalize_symbol(symbol)
        try:
            ticker = await binance_service.get_ticker(symbol_ccxt)
            current_price = ticker.price
        except Exception:
            # Fallback: get from positions
            positions = await paper_trading_service.get_positions()
            pos = next((p for p in positions if p["symbol"] == symbol), None)
            if pos:
                current_price = pos["avg_price"]
            else:
                raise HTTPException(status_code=404, detail=f"No position for {symbol}")

        analysis = await position_analysis_service.get_position_analytics(
            symbol, current_price
        )
        if not analysis:
            raise HTTPException(status_code=404, detail=f"No position for {symbol}")

        return analysis
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to analyze position: {e}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Data Export
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/export/trades")
async def export_trades(
    format: str = Query("json", pattern="^(json|csv)$"),
    limit: int = Query(500, ge=1, le=5000),
):
    """Export trade pairs data as JSON or CSV."""
    pairs = await trade_pair_service.get_trade_pairs(limit=limit)

    if format == "csv":
        import io
        import csv
        from fastapi.responses import StreamingResponse

        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "pair_id", "symbol", "side", "status",
                "entry_price", "exit_price", "quantity",
                "entry_time", "exit_time",
                "pnl", "pnl_pct", "holding_hours", "holding_costs",
            ],
        )
        writer.writeheader()
        for p in pairs:
            writer.writerow({
                "pair_id": p.get("pair_id"),
                "symbol": p.get("symbol"),
                "side": p.get("side"),
                "status": p.get("status"),
                "entry_price": p.get("entry_price"),
                "exit_price": p.get("exit_price"),
                "quantity": p.get("quantity"),
                "entry_time": p.get("entry_time"),
                "exit_time": p.get("exit_time"),
                "pnl": p.get("pnl"),
                "pnl_pct": p.get("pnl_pct"),
                "holding_hours": p.get("holding_hours"),
                "holding_costs": p.get("holding_costs"),
            })

        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=trades_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            },
        )

    return {"trades": pairs, "total": len(pairs)}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_symbol(symbol: str) -> str:
    """Convert 'BTCUSDT' to 'BTC/USDT' for ccxt."""
    symbol = symbol.upper()
    if "/" not in symbol:
        for quote in ("USDT", "BTC", "ETH", "BNB", "BUSD"):
            if symbol.endswith(quote):
                base = symbol[: -len(quote)]
                return f"{base}/{quote}"
    return symbol
