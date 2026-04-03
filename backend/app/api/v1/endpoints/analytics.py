"""
Analytics Endpoints
Provides performance metrics, equity curve, trade pairs, and position analysis.
"""

import logging
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
from app.models.db_models import EquitySnapshot, PaperTrade, ReplaySession

from sqlalchemy import select

logger = logging.getLogger(__name__)

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
    period: str = Query("all_time", pattern="^(daily|today|weekly|monthly|all_time)$"),
    include_mock: bool = Query(False, description="Include mock/demo data"),
    replay_session_id: Optional[str] = Query(None, description="回放会话ID，提供时返回该会话的指标"),
):
    """Get aggregated performance metrics for a given period."""
    cache_key = f"{REDIS_PERF_KEY.format(period=period)}:{include_mock}:{replay_session_id or 'global'}"
    
    # Skip cache when replay_session_id is provided to ensure fresh data
    if not replay_session_id:
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
        # When replay_session_id is provided, query for that specific session
        if replay_session_id:
            async with get_db() as session:
                stmt = select(ReplaySession).where(
                    ReplaySession.replay_session_id == replay_session_id
                )
                result = await session.execute(stmt)
                replay_session = result.scalar_one_or_none()

            if not replay_session:
                raise HTTPException(
                    status_code=404,
                    detail=f"Replay session '{replay_session_id}' not found"
                )

            # Use replay session's initial_capital
            initial_capital = Decimal(str(replay_session.initial_capital or 100000.0))

            # Use replay session's actual time range instead of period-based range
            replay_start = replay_session.start_time
            replay_end = replay_session.end_time or now
            # Ensure timezone-aware
            if replay_start is not None and replay_start.tzinfo is None:
                replay_start = replay_start.replace(tzinfo=timezone.utc)
            if replay_end is not None and replay_end.tzinfo is None:
                replay_end = replay_end.replace(tzinfo=timezone.utc)

            metrics = await performance_service.calculate_metrics(
                replay_start, replay_end, initial_capital, session_id=replay_session_id
            )
            # Add replay_session_id to indicate data source
            metrics["replay_session_id"] = replay_session_id
        else:
            # Global aggregation (original behavior)
            metrics = await performance_service.calculate_metrics(
                start, now, Decimal("100000")
            )

        # Skip cache write when replay_session_id is provided
        if not replay_session_id:
            await redis_set(cache_key, metrics, ttl=CACHE_TTL)
        
        # Log key metrics before returning
        logger.info(
            f"Performance metrics returned: session_id={replay_session_id}, "
            f"total_trades={metrics.get('total_trades')}, "
            f"win_rate={metrics.get('win_rate')}, "
            f"total_return={metrics.get('total_return')}%"
        )
        
        return metrics
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to calculate metrics: {e}")


@router.get("/attribution")
async def get_attribution(
    period: str = Query("all_time", pattern="^(daily|today|weekly|monthly|all_time)$")
):
    """Get profit attribution by strategy."""
    import logging
    logger = logging.getLogger(__name__)
    
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
        logger.error(f"Failed to get attribution for period={period}: {e}", exc_info=True)
        # 返回空数据而非500错误
        return {
            "attribution": [],
            "message": f"归因数据暂不可用: {str(e)}",
            "error": str(e)
        }


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
    import logging
    logger = logging.getLogger(__name__)
    
    # 空数据返回结构
    empty_result = {
        "strategy_id": strategy_id,
        "symbol": symbol,
        "base_mode": base_mode,
        "compare_mode": compare_mode,
        "replay_session_id": replay_session_id,
        "daily": [],
        "symbol": [],
        "global": {
            "bt_total_pnl": 0,
            "sim_total_pnl": 0,
            "delta_price": 0,
            "delta_fill": 0,
            "delta_timing": 0,
            "delta_fees": 0,
            "delta_total": 0,
        },
        "signal_level_details": [],
        "trades": [],
    }
    
    try:
        # 检查 historical_replay 模式是否需要 session_id
        if compare_mode == "historical_replay" and not replay_session_id:
            logger.warning(f"Strategy attribution: session_id required for historical_replay mode, strategy={strategy_id}")
            return {
                **empty_result,
                "message": "历史回放模式需要提供 replay_session_id 参数",
                "error": "replay_session_id is required when compare_mode is 'historical_replay'"
            }
        
        report = await attribution_service.get_strategy_attribution(
            strategy_id=strategy_id,
            symbol=symbol,
            days=days,
            base_mode=base_mode,
            compare_mode=compare_mode,
            replay_session_id=replay_session_id
        )
        
        # 处理服务层返回的错误
        if report and "error" in report and report["error"]:
            logger.warning(f"Strategy attribution error for strategy={strategy_id}: {report['error']}")
            return {
                **empty_result,
                **report,  # 保留原有数据结构
                "message": f"归因分析数据不可用: {report['error']}",
            }
        
        return report
    except Exception as e:
        logger.error(f"Failed to get attribution report for strategy={strategy_id}: {e}", exc_info=True)
        return {
            **empty_result,
            "message": f"归因分析暂不可用: {str(e)}",
            "error": str(e)
        }


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
    session_id: Optional[str] = Query(None, description="Filter by session ID for historical replay"),
    include_mock: bool = Query(False, description="Include mock/demo data"),
):
    """Get equity curve data points for charting."""
    cache_key = f"{REDIS_EQUITY_KEY.format(period=period)}:{interval}:{session_id or 'all'}:{include_mock}"
    
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
        query = (
            select(EquitySnapshot)
            .where(EquitySnapshot.timestamp >= start)
            .where(EquitySnapshot.timestamp <= now)
        )
        if session_id:
            query = query.where(EquitySnapshot.session_id == session_id)
        if not include_mock:
            query = query.where(EquitySnapshot.data_source != 'MOCK')
        query = query.order_by(EquitySnapshot.timestamp.asc())
        
        result = await session.execute(query)
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


# ─────────────────────────────────────────────────────────────────────────────
# Replay Quick Backtest — 自动用相同条件运行回测
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/replay-quick-backtest")
async def replay_quick_backtest(replay_session_id: str):
    """
    从一个已完成的历史回放会话中提取参数，
    自动运行一次相同条件（相同币种、周期、策略、参数、时间范围）的回测，
    并将回测结果存储到数据库。

    用于"快速对比回测"功能：点击按钮后自动完成回测，跳转到性能分析界面直接对比。
    """
    from app.models.db_models import BacktestResult, ReplaySession
    from app.services.strategy_templates import get_template, build_signal_func

    async with get_db() as session:
        # 1. 获取 replay session
        stmt = select(ReplaySession).where(ReplaySession.replay_session_id == replay_session_id)
        result = await session.execute(stmt)
        replay = result.scalar_one_or_none()

        if not replay:
            raise HTTPException(status_code=404, detail="回放会话不存在")

        if replay.status not in ("completed", "failed"):
            raise HTTPException(
                status_code=400,
                detail=f"回放会话状态为 '{replay.status}'，仅支持已完成或已失败的会话"
            )

        # 2. 提取参数
        symbol = replay.symbol.upper()
        strategy_type = replay.strategy_type
        params = replay.params or {}

        # 从 params 中提取 interval（回放界面会将 interval 存入 params）
        interval = params.get("interval", "1m")

        # 获取时间范围
        start_time = replay.start_time
        end_time = replay.end_time
        if not start_time or not end_time:
            raise HTTPException(status_code=400, detail="回放会话缺少时间范围信息")

        # 计算需要的 K 线数量
        interval_seconds = {
            "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
            "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600,
            "8h": 28800, "12h": 43200,
            "1d": 86400, "3d": 259200, "1w": 604800, "1M": 2592000,
        }.get(interval, 60)

        total_seconds = (end_time - start_time).total_seconds()
        estimated_limit = int(total_seconds / interval_seconds) + 10  # +10 buffer

        # 应用安全上限
        MAX_LIMITS = {
            "1m": 10000, "5m": 5000, "15m": 3000, "30m": 2000,
            "1h": 2000, "2h": 2000, "4h": 2000, "6h": 2000,
            "8h": 2000, "12h": 2000,
            "1d": 2000, "3d": 2000, "1w": 2000, "1M": 2000,
        }
        max_limit = MAX_LIMITS.get(interval, 2000)
        limit = min(estimated_limit, max_limit)
        limit = max(limit, 50)  # 至少 50 根

        initial_capital = float(replay.initial_capital) if replay.initial_capital else 100000.0

    # 3. 验证策略类型（不支持异步策略）
    async_strategies = {"smart_beta", "basis"}
    if strategy_type in async_strategies:
        raise HTTPException(
            status_code=400,
            detail=f"策略 '{strategy_type}' 为异步策略，不支持回测对比。"
        )

    try:
        get_template(strategy_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"不支持的策略类型: {strategy_type}")

    # 4. 获取 Binance K 线数据（从 start_time 开始取 limit 根）
    from app.services.binance_service import binance_service

    symbol_ccxt = symbol
    if "/" not in symbol_ccxt:
        for quote in ("USDT", "BTC", "ETH", "BNB", "BUSD"):
            if symbol_ccxt.endswith(quote):
                symbol_ccxt = f"{symbol_ccxt[:-len(quote)]}/{quote}"
                break

    # 使用 start_time 从 Binance 获取数据
    df = await binance_service.get_klines_dataframe(
        symbol_ccxt, interval, limit=limit, start=start_time, end=end_time
    )

    if df is None or len(df) < 50:
        raise HTTPException(status_code=400, detail="回测数据不足（需要至少 50 根 K 线）")

    if len(df) < 20:
        raise HTTPException(status_code=400, detail="回测区间内数据不足（需要至少 20 根 K 线）")

    # 5. 构建信号函数并运行回测
    from app.services.strategy_templates import build_signal_func
    signal_func = build_signal_func(strategy_type, params)

    # 使用 strategy endpoint 中的 engine
    from app.api.v1.endpoints.strategy import _run_backtest_engine, _buy_and_hold_signal, _normalize_symbol
    result = _run_backtest_engine(
        df=df,
        signal_func=signal_func,
        initial_capital=initial_capital,
        symbol=symbol,
        timeframe=interval,
    )

    # 买入门卫基准
    baseline_result = _run_backtest_engine(
        df=df,
        signal_func=_buy_and_hold_signal,
        initial_capital=initial_capital,
        symbol=symbol,
        timeframe=interval,
    )

    # 6. 构造 equity curve（downsampled）
    equity_values = result["equity_curve"]
    step = max(1, len(equity_values) // 500)
    equity_curve = [
        {"t": str(df.index[i])[:19], "v": round(equity_values[i], 2)}
        for i in range(0, len(equity_values), step)
    ]

    # 7. 构造 markers
    trades_list = result["trades"]
    markers = []
    for t in trades_list:
        markers.append({"time": t["entry_time"], "price": t["entry_price"], "side": "BUY", "pnl": None})
        markers.append({"time": t["exit_time"], "price": t["exit_price"], "side": "SELL", "pnl": t["pnl"]})
    markers.sort(key=lambda x: x["time"])

    # 8. 持久化到数据库
    import hashlib, json
    params_json = json.dumps(params, sort_keys=True)
    params_hash = hashlib.sha256(params_json.encode()).hexdigest()

    metrics_dict = {
        "total_return": result["total_return"],
        "annual_return": result["annual_return"],
        "max_drawdown": result["max_drawdown"],
        "sharpe_ratio": result["sharpe_ratio"],
        "win_rate": result["win_rate"],
        "profit_factor": result["profit_factor"],
        "total_trades": result["total_trades"],
        "total_commission": result.get("total_commission", 0.0),
        "initial_capital": initial_capital,
        "final_capital": result["final_capital"],
    }

    backtest_db_id = None
    async with get_db() as session:
        bt_row = BacktestResult(
            strategy_type=strategy_type,
            symbol=symbol,
            interval=interval,
            params=params,
            params_hash=params_hash,
            metrics=metrics_dict,
            equity_curve=equity_curve[:2000],
            trades_summary=trades_list[:100],
            data_source="REPLAY_COMPARE",  # 标记为"快速对比回测"生成
        )
        session.add(bt_row)
        await session.flush()
        backtest_db_id = bt_row.id
        await session.commit()

    import logging
    logger = logging.getLogger(__name__)
    logger.info(
        f"[快速对比回测] replay={replay_session_id} -> backtest_id={backtest_db_id} | "
        f"{symbol}/{interval} | {strategy_type} | {len(trades_list)}笔交易 | "
        f"收益率={result['total_return']:.2f}%"
    )

    return {
        "replay_session_id": replay_session_id,
        "backtest_id": backtest_db_id,
        "strategy_type": strategy_type,
        "symbol": symbol,
        "interval": interval,
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "params": params,
        "metrics": metrics_dict,
        "total_trades": result["total_trades"],
        "equity_curve_sample": equity_curve[:20],  # 前20个点用于前端预览
    }


# ─────────────────────────────────────────────────────────────────────────────
# Replay vs Backtest Comparison
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/replay-backtest-comparison")
async def get_replay_backtest_comparison(
    replay_session_id: Optional[str] = Query(None, description="Specific replay session ID"),
    backtest_id: Optional[int] = Query(None, description="Specific backtest record ID"),
    symbol: Optional[str] = Query(None, description="Filter by symbol (e.g. BTCUSDT)"),
    limit: int = Query(10, ge=1, le=50, description="Max comparisons to return"),
    include_mock: bool = Query(False, description="Include mock data"),
):
    """
    获取回放与回测的详细对比数据。

    匹配优先级：explicit backtest_id > params_hash exact match > symbol+strategy_type fuzzy match
    """
    from app.models.db_models import BacktestResult, PaperTrade, ReplaySession
    from app.services.database import get_db
    from app.services.replay_metrics_service import replay_metrics_service
    import hashlib, json

    async with get_db() as session:
        # 1. Resolve replay session
        if replay_session_id:
            stmt = select(ReplaySession).where(ReplaySession.replay_session_id == replay_session_id)
        else:
            stmt = select(ReplaySession).where(ReplaySession.is_saved == True).order_by(ReplaySession.created_at.desc()).limit(1)

        result = await session.execute(stmt)
        replay = result.scalar_one_or_none()

        if not replay:
            raise HTTPException(
                status_code=404,
                detail="No replay session found. Please run a historical replay first."
            )

        # 2. Always compute replay metrics in real-time (never trust cached replay.metrics)
        # The cached metrics field may be stale or from a different session's data
        computed = True
        try:
            logger.info(f"[Replay Metrics] Computing metrics in real-time for session {replay.replay_session_id}")
            replay_metrics = await replay_metrics_service.compute_and_store_metrics(replay.replay_session_id)
            logger.info(f"[Replay Metrics] Computed metrics for {replay.replay_session_id}: total_trades={replay_metrics.get('total_trades', 'N/A')}, total_return={replay_metrics.get('total_return', 'N/A')}")
        except Exception as e:
            logger.error(f"[Replay Metrics] Failed to compute metrics for {replay.replay_session_id}: {e}", exc_info=True)
            # Return explicit error instead of falling back to mock/cached data
            raise HTTPException(
                status_code=500,
                detail=f"Failed to compute replay metrics: {str(e)}"
            )

        # 3. Build basic replay info
        replay_info = {
            "replay_session_id": replay.replay_session_id,
            "strategy_type": replay.strategy_type,
            "symbol": replay.symbol,
            "start_time": replay.start_time.isoformat() if replay.start_time else None,
            "end_time": replay.end_time.isoformat() if replay.end_time else None,
            "initial_capital": float(replay.initial_capital) if replay.initial_capital else 100000.0,
            "status": replay.status,
            "created_at": replay.created_at.isoformat() if replay.created_at else None,
            "data_source": replay.data_source if hasattr(replay, 'data_source') else 'REPLAY',
            "params_hash": replay.params_hash if hasattr(replay, 'params_hash') else None,
            "backtest_id": replay.backtest_id if hasattr(replay, 'backtest_id') else None,
            "params": replay.params or {},
            "metrics_computed": computed,
        }

        # 4. Resolve backtest records with improved matching logic
        backtest_records = []
        match_message = None  # 匹配结果提示信息

        # Priority 1: 使用 session.backtest_id 直接关联，或 API 参数明确传入的 backtest_id
        resolved_backtest_id = backtest_id or (replay.backtest_id if hasattr(replay, 'backtest_id') and replay.backtest_id else None)
        
        if resolved_backtest_id:
            stmt = select(BacktestResult).where(BacktestResult.id == resolved_backtest_id)
            result = await session.execute(stmt)
            bt = result.scalar_one_or_none()
            if bt:
                backtest_records.append(bt)
                logger.info(f"[回测匹配] 优先级1: 通过 backtest_id={resolved_backtest_id} 直接关联成功")
            else:
                # backtest_id 指定但未找到，记录警告但继续尝试其他匹配方式
                logger.warning(f"[回测匹配] 优先级1: backtest_id={resolved_backtest_id} 未找到，尝试其他匹配方式")

        # Priority 2: 按策略类型 + 币种匹配最新回测
        if not backtest_records and replay.strategy_type and replay.symbol:
            conditions = [
                BacktestResult.strategy_type == replay.strategy_type,
                BacktestResult.symbol == replay.symbol.upper()
            ]
            if not include_mock:
                conditions.append(BacktestResult.data_source != 'MOCK')
            
            stmt = (
                select(BacktestResult)
                .where(*conditions)
                .order_by(BacktestResult.created_at.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            bt = result.scalar_one_or_none()
            if bt:
                backtest_records.append(bt)
                logger.info(f"[回测匹配] 优先级2: 按 strategy_type={replay.strategy_type}, symbol={replay.symbol} 匹配到 backtest_id={bt.id}")

        # Priority 3: 明确返回无匹配（不再返回不相关策略/币种的回测记录）
        if not backtest_records:
            match_message = "未找到匹配的回测记录，请先执行快速对比回测"
            logger.info(f"[回测匹配] 优先级3: 无匹配，strategy_type={replay.strategy_type}, symbol={replay.symbol}")

        # 5. Compute param diffs for the primary match
        # 修复 null 值处理：用"未记录"代替 null，避免误导信息
        primary_bt = backtest_records[0] if backtest_records else None
        replay_params = replay.params or {}
        bt_params = dict(primary_bt.params) if primary_bt and primary_bt.params else {}
        
        # 重要：将 interval 字段合并到 bt_params 中进行比较
        # BacktestResult 有独立的 interval 字段，需要加入 params 进行参数对比
        if primary_bt and primary_bt.interval:
            bt_params["interval"] = primary_bt.interval
        
        param_diff = {}
        if bt_params or replay_params:
            all_keys = set(list(replay_params.keys()) + list(bt_params.keys()))
            for key in all_keys:
                replay_val = replay_params.get(key)
                backtest_val = bt_params.get(key) if bt_params else None
                
                # 如果两边都是 None 或相等，不记录差异
                if replay_val == backtest_val:
                    continue
                
                # 如果一方未记录而另一方有值，用"未记录"代替 null
                if backtest_val is None and replay_val is not None:
                    param_diff[key] = {"replay": replay_val, "backtest": "未记录"}
                elif replay_val is None and backtest_val is not None:
                    param_diff[key] = {"replay": "未记录", "backtest": backtest_val}
                elif replay_val != backtest_val and replay_val is not None and backtest_val is not None:
                    param_diff[key] = {"replay": replay_val, "backtest": backtest_val}

        # 6. Compute time overlap
        time_overlap_pct = None
        if primary_bt and replay.start_time and replay.end_time and primary_bt.created_at:
            # Rough overlap estimate based on replay period vs backtest creation time
            replay_duration = (replay.end_time - replay.start_time).days
            bt_duration = 180  # assume ~6 months for backtest
            overlap = min(replay_duration, bt_duration) / max(replay_duration, bt_duration)
            time_overlap_pct = round(overlap * 100, 2)

        # 7. Build comparisons with 10+ metrics (including max_drawdown_duration)
        # 当 backtest_record 为 null 时，所有 deltas 也应为 null
        METRICS_TO_COMPARE = [
            ("total_return", "总收益率 (%)", "max2"),
            ("annualized_return", "年化收益率 (%)", "max2"),
            ("max_drawdown", "最大回撤 (金额)", "min3"),
            ("max_drawdown_pct", "最大回撤 (%)", "min2"),
            ("max_drawdown_duration", "最大回撤持续天数", "min2"),
            ("sharpe_ratio", "夏普比率", "max2"),
            ("sortino_ratio", "索提诺比率", "max2"),
            ("calmar_ratio", "卡玛比率", "max2"),
            ("volatility", "波动率 (%)", "min2"),
            ("win_rate", "胜率 (%)", "max2"),
            ("profit_factor", "盈亏比", "max2"),
            ("total_trades", "交易次数", "neutral"),
            ("final_equity", "最终权益", "max2"),
            ("var_95", "VaR 95% (%)", "min2"),
        ]

        # 定义 key 映射（replay key -> 可能的 backtest key 别名）
        # 扩展的别名映射，确保各种字段名称都能匹配
        KEY_ALIASES = {
            "total_return": ["total_return", "total_return_pct", "return_pct", "total_pnl_pct"],
            "annualized_return": ["annualized_return", "annualized_return_pct", "annual_return"],
            "max_drawdown": ["max_drawdown", "max_dd", "maximum_drawdown", "max_drawdown_amount"],
            "max_drawdown_pct": ["max_drawdown_pct", "max_dd_pct", "max_drawdown_percent"],
            "max_drawdown_duration": ["max_drawdown_duration", "max_dd_duration", "max_drawdown_days"],
            "sharpe_ratio": ["sharpe_ratio", "sharpe"],
            "sortino_ratio": ["sortino_ratio", "sortino"],
            "calmar_ratio": ["calmar_ratio", "calmar"],
            "volatility": ["volatility", "vol", "annual_volatility"],
            "win_rate": ["win_rate", "win_ratio", "winning_rate"],
            "profit_factor": ["profit_factor", "profit_loss_ratio", "pnl_ratio"],
            "total_trades": ["total_trades", "trade_count", "num_trades"],
            "final_equity": ["final_equity", "ending_equity", "final_capital", "end_equity"],
            "var_95": ["var_95", "value_at_risk", "var_95_pct"],
        }

        def get_metric_value(metrics_dict, metric_key):
            """从metrics字典中获取值，支持别名查找"""
            if not metrics_dict:
                return None
            # 直接查找
            val = metrics_dict.get(metric_key)
            if val is not None:
                return val
            # 别名查找
            aliases = KEY_ALIASES.get(metric_key, [])
            for alias in aliases:
                val = metrics_dict.get(alias)
                if val is not None:
                    return val
            return None

        def _enrich_backtest_metrics(bt_record, bt_metrics_dict):
            """从其他来源补充缺失的 backtest metrics"""
            if not bt_record:
                return bt_metrics_dict
            
            enriched = dict(bt_metrics_dict) if bt_metrics_dict else {}
            
            # 补充 total_trades：从 trades_summary 长度推算
            if get_metric_value(enriched, "total_trades") is None:
                trades_summary = bt_record.trades_summary or []
                if isinstance(trades_summary, list) and len(trades_summary) > 0:
                    enriched["total_trades"] = len(trades_summary)
                    logger.debug(f"Enriched total_trades from trades_summary: {len(trades_summary)}")
            
            # 补充 win_rate：从 trades_summary 计算盈利交易比例
            if get_metric_value(enriched, "win_rate") is None:
                trades_summary = bt_record.trades_summary or []
                if isinstance(trades_summary, list) and len(trades_summary) > 0:
                    winning_trades = [t for t in trades_summary if t.get("pnl") and float(t.get("pnl", 0)) > 0]
                    enriched["win_rate"] = round(len(winning_trades) / len(trades_summary) * 100, 2)
                    logger.debug(f"Enriched win_rate from trades_summary: {enriched['win_rate']}%")
            
            # 补充 final_equity：从 equity_curve 最后一个点获取
            if get_metric_value(enriched, "final_equity") is None:
                equity_curve = bt_record.equity_curve or []
                if isinstance(equity_curve, list) and len(equity_curve) > 0:
                    last_point = equity_curve[-1]
                    final_val = last_point.get("v") or last_point.get("equity") or last_point.get("value")
                    if final_val is not None:
                        enriched["final_equity"] = float(final_val)
                        logger.debug(f"Enriched final_equity from equity_curve: {enriched['final_equity']}")
            
            return enriched

        # 使用 _enrich_backtest_metrics 补充缺失指标
        bt_metrics = _enrich_backtest_metrics(primary_bt, (primary_bt.metrics or {}) if primary_bt else {})

        comparisons = []
        for metric_key, metric_label, better_direction in METRICS_TO_COMPARE:
            r_val = replay_metrics.get(metric_key)
            
            # 使用 get_metric_value 支持别名查找
            b_val = get_metric_value(bt_metrics, metric_key) if primary_bt else None

            if primary_bt is None:
                # 无回测记录，delta 为 null
                delta = None
                interpretation = "无回测数据可比"
            elif r_val is not None and b_val is not None:
                delta = float(r_val) - float(b_val)
                if better_direction == "max2" and delta > 0:
                    interpretation = "回放优于回测"
                elif better_direction == "max2" and delta < 0:
                    interpretation = "回放劣于回测"
                elif better_direction == "min2" and delta < 0:
                    interpretation = "回放优于回测"
                elif better_direction == "min2" and delta > 0:
                    interpretation = "回放劣于回测"
                else:
                    interpretation = "基本持平"
            else:
                delta = None
                interpretation = "数据不可比"

            comparisons.append({
                "metric": metric_key,
                "label": metric_label,
                "replay_value": r_val,
                "backtest_value": b_val,
                "delta": delta,
                "interpretation": interpretation,
            })

        # 8. Get trade-level comparison data if both replay and backtest have trades
        trade_level_comparison = []
        replay_trades_count = 0
        backtest_trades_count = 0
        
        # Get replay trades from paper_trades (使用 session_id 过滤确保数据准确)
        stmt_replay_trades = (
            select(PaperTrade)
            .where(PaperTrade.session_id == replay.replay_session_id)
            .order_by(PaperTrade.created_at.asc())
            .limit(100)
        )
        result_trades = await session.execute(stmt_replay_trades)
        replay_trades = result_trades.scalars().all()
        replay_trades_count = len(replay_trades)
        
        # Get backtest trades from trades_summary (仅当有匹配的回测记录时)
        bt_trades_summary = (primary_bt.trades_summary or []) if primary_bt else []
        backtest_trades_count = len(bt_trades_summary)
        
        # Align trades by timestamp for detailed comparison
        if replay_trades and bt_trades_summary:
            for i, replay_trade in enumerate(replay_trades[:min(20, len(replay_trades))]):
                # Try to find matching backtest trade by time proximity
                replay_time = replay_trade.created_at
                best_match = None
                best_diff = float('inf')
                
                for bt_trade in bt_trades_summary:
                    try:
                        bt_entry_time = datetime.fromisoformat(bt_trade.get('entry_time', '').replace('Z', '+00:00'))
                        time_diff = abs((replay_time - bt_entry_time).total_seconds())
                        if time_diff < best_diff and time_diff < 3600:  # Within 1 hour
                            best_diff = time_diff
                            best_match = bt_trade
                    except (ValueError, TypeError):
                        continue
                
                # 计算差异值
                delta_price = None
                delta_qty = None
                time_diff_seconds = None
                if best_match:
                    delta_price = round(float(replay_trade.price or 0) - float(best_match.get('entry_price', 0) or 0), 4)
                    delta_qty = round(float(replay_trade.quantity or 0) - float(best_match.get('quantity', 0) or 0), 8)
                    time_diff_seconds = round(best_diff, 2)
                
                # 使用嵌套结构构建交易对比记录
                trade_comparison = {
                    "index": i,
                    "replay_trade": {
                        "timestamp": replay_time.isoformat() if replay_time else None,
                        "side": replay_trade.side,
                        "price": float(replay_trade.price) if replay_trade.price else 0,
                        "quantity": float(replay_trade.quantity) if replay_trade.quantity else 0,
                        "fee": float(replay_trade.fee) if replay_trade.fee else 0,
                    },
                    "backtest_trade": {
                        "timestamp": best_match.get("entry_time") if best_match else None,
                        "price": float(best_match.get("entry_price", 0) or 0) if best_match else None,
                        "quantity": float(best_match.get("quantity", 0) or 0) if best_match else None,
                        "pnl": best_match.get("pnl") if best_match else None,
                    } if best_match else None,
                    "delta_price": delta_price,
                    "delta_quantity": delta_qty,
                    "time_diff_seconds": time_diff_seconds,
                }
                
                trade_level_comparison.append(trade_comparison)

        # 确定匹配类型
        if not backtest_records:
            match_type = "no_match"
        elif resolved_backtest_id:
            match_type = "explicit_id"
        else:
            match_type = "strategy_symbol"

        return {
            "replay_session": replay_info,
            "replay_metrics": replay_metrics,
            "backtest_record": {
                "id": primary_bt.id,
                "strategy_type": primary_bt.strategy_type,
                "symbol": primary_bt.symbol,
                "interval": primary_bt.interval,
                "created_at": primary_bt.created_at.isoformat() if primary_bt.created_at else None,
                "data_source": primary_bt.data_source if hasattr(primary_bt, 'data_source') else 'BACKTEST',
                "params": primary_bt.params or {},
                "metrics": primary_bt.metrics or {},
            } if primary_bt else None,
            "backtest_results": [
                {
                    "id": bt.id,
                    "strategy_type": bt.strategy_type,
                    "symbol": bt.symbol,
                    "interval": bt.interval,
                    "created_at": bt.created_at.isoformat() if bt.created_at else None,
                    "data_source": bt.data_source if hasattr(bt, 'data_source') else 'BACKTEST',
                    "params": bt.params or {},
                    "metrics": bt.metrics or {},
                }
                for bt in backtest_records
            ],
            "comparisons": comparisons,
            "trade_level_comparison": trade_level_comparison,
            "replay_trades_count": replay_trades_count,
            "backtest_trades_count": backtest_trades_count,
            "param_diff": param_diff,
            "time_overlap_pct": time_overlap_pct,
            "match_type": match_type,
            "message": match_message,
        }


@router.get("/replay-backtest-equity")
async def get_replay_backtest_equity(
    replay_session_id: str = Query(..., description="Replay session ID"),
    backtest_id: Optional[int] = Query(None, description="Specific backtest record ID"),
    symbol: Optional[str] = Query(None, description="Symbol to match backtest"),
    include_mock: bool = Query(False, description="Include mock data"),
):
    """获取回放与回测的权益曲线数据用于叠加对比图。"""
    from app.models.db_models import BacktestResult, PaperTrade, ReplaySession, EquitySnapshot
    from app.services.database import get_db
    from app.services.replay_metrics_service import replay_metrics_service

    async with get_db() as session:
        # 1. Get replay session
        stmt = select(ReplaySession).where(ReplaySession.replay_session_id == replay_session_id)
        result = await session.execute(stmt)
        replay_session = result.scalar_one_or_none()

        if not replay_session:
            raise HTTPException(status_code=404, detail="Replay session not found")

        # 2. Resolve backtest_id
        bt_id = backtest_id
        if not bt_id:
            bt_id = replay_session.backtest_id if hasattr(replay_session, 'backtest_id') and replay_session.backtest_id else None

        # 3. Get replay equity from EquitySnapshot
        stmt = (
            select(EquitySnapshot)
            .where(EquitySnapshot.session_id == replay_session_id)
            .order_by(EquitySnapshot.timestamp.asc())
        )
        if not include_mock:
            stmt = stmt.where(EquitySnapshot.data_source != 'MOCK')
        result = await session.execute(stmt)
        replay_snapshots = result.scalars().all()

        replay_equity = []
        for s in replay_snapshots:
            replay_equity.append({
                "timestamp": s.timestamp.isoformat() if s.timestamp else None,
                "total_equity": float(s.total_equity) if s.total_equity else 0,
                "equity": float(s.total_equity) if s.total_equity else 0,  # 前端兼容别名
                "cash_balance": float(s.cash_balance) if s.cash_balance else 0,
            })

        # 4. Get backtest record
        # When bt_id is explicitly provided, query by ID only (no additional filters)
        if bt_id:
            stmt = select(BacktestResult).where(BacktestResult.id == bt_id)
            result = await session.execute(stmt)
            backtest_record = result.scalar_one_or_none()
            if not backtest_record:
                raise HTTPException(
                    status_code=404,
                    detail=f"Backtest record with id={bt_id} not found."
                )
        else:
            # No explicit bt_id, use fuzzy matching
            bt_conditions = []
            if symbol:
                bt_conditions.append(BacktestResult.symbol == symbol.upper())
            if replay_session.strategy_type:
                bt_conditions.append(BacktestResult.strategy_type == replay_session.strategy_type)
            if not include_mock:
                bt_conditions.append(BacktestResult.data_source != 'MOCK')

            if bt_conditions:
                stmt = select(BacktestResult).where(*bt_conditions).order_by(BacktestResult.created_at.desc()).limit(1)
            else:
                stmt = select(BacktestResult).order_by(BacktestResult.created_at.desc()).limit(1)

            result = await session.execute(stmt)
            backtest_record = result.scalar_one_or_none()

        backtest_equity = []
        if backtest_record and backtest_record.equity_curve:
            for point in backtest_record.equity_curve:
                backtest_equity.append({
                    "timestamp": point.get("t") or point.get("timestamp") or point.get("time"),
                    "equity": round(float(point.get("v", point.get("equity", 0))), 2),
                })

        # 5. Normalize both curves to relative return percentage (initial = 0%)
        # Formula: return_pct = ((equity / initial_equity) - 1) * 100
        normalized_replay = []
        normalized_backtest = []

        if replay_equity:
            initial_re = replay_equity[0]["total_equity"] or 1
            for idx, p in enumerate(replay_equity):
                pct = ((p["total_equity"] / initial_re) - 1) * 100 if initial_re > 0 else 0
                normalized_replay.append({
                    "index": idx,  # 相对时间索引
                    "timestamp": p["timestamp"],  # 保留原始时间戳供 hover 显示
                    "return_pct": round(pct, 4),
                })

        if backtest_equity:
            initial_bt = backtest_equity[0]["equity"] or 1
            for idx, p in enumerate(backtest_equity):
                pct = ((p["equity"] / initial_bt) - 1) * 100 if initial_bt > 0 else 0
                normalized_backtest.append({
                    "index": idx,  # 相对时间索引
                    "timestamp": p["timestamp"],  # 保留原始时间戳供 hover 显示
                    "return_pct": round(pct, 4),
                })

        # 6. Align array lengths (pad shorter curve with its last value)
        len_replay = len(normalized_replay)
        len_backtest = len(normalized_backtest)
        max_length = max(len_replay, len_backtest)

        if len_replay < max_length and len_replay > 0:
            last_point = normalized_replay[-1]
            for i in range(len_replay, max_length):
                normalized_replay.append({
                    "index": i,
                    "timestamp": last_point["timestamp"],  # 使用最后一个时间戳
                    "return_pct": last_point["return_pct"],  # flat-line extension
                })

        if len_backtest < max_length and len_backtest > 0:
            last_point = normalized_backtest[-1]
            for i in range(len_backtest, max_length):
                normalized_backtest.append({
                    "index": i,
                    "timestamp": last_point["timestamp"],  # 使用最后一个时间戳
                    "return_pct": last_point["return_pct"],  # flat-line extension
                })

        return {
            "replay_session_id": replay_session_id,
            "backtest_id": backtest_record.id if backtest_record else None,
            "replay_equity": replay_equity,
            "backtest_equity": backtest_equity,
            "normalized_replay": normalized_replay,
            "normalized_backtest": normalized_backtest,
            "max_length": max_length,  # 对齐后的数据点数
            "config": {
                "replay_initial_capital": float(replay_session.initial_capital) if replay_session.initial_capital else 100000.0,
                "backtest_initial_capital": float((backtest_record.metrics or {}).get("initial_capital", replay_session.initial_capital or 100000.0)) if backtest_record else replay_session.initial_capital or 100000.0,
                "symbol": replay_session.symbol,
                "strategy_type": replay_session.strategy_type,
                "replay_data_source": replay_session.data_source if hasattr(replay_session, 'data_source') else 'REPLAY',
                "backtest_data_source": backtest_record.data_source if backtest_record and hasattr(backtest_record, 'data_source') else 'BACKTEST',
            }
        }


# ─────────────────────────────────────────────────────────────────────────────
# Attribution Comparison API
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/attribution/comparison")
async def get_attribution_comparison(
    strategy_id: str = Query(..., description="Strategy ID (e.g., auto_trend_ma)"),
    base_mode: str = Query("backtest", description="Base mode for comparison"),
    compare_mode: str = Query("historical_replay", pattern="^(historical_replay|paper)$"),
    session_id: Optional[str] = Query(None, description="Replay session ID (required for historical_replay mode)"),
    symbol: Optional[str] = Query(None, description="Filter by symbol (e.g., BTCUSDT)"),
    days: int = Query(7, ge=1, le=90, description="Time range in days"),
):
    """
    获取两个模式下的归因数据对比。
    
    返回包含：
    - 价格差异 (delta_price)
    - 成交率差异 (delta_fill)
    - 手续费差异 (delta_fees)
    - 滑点影响 (slippage_impact)
    - 延迟影响 (latency_impact)
    - 执行质量评分 (execution_quality)
    - 执行延迟 (timing_diff)
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # 空数据返回结构
    empty_result = {
        "strategy_id": strategy_id,
        "base_mode": base_mode,
        "compare_mode": compare_mode,
        "session_id": session_id,
        "symbol": symbol,
        "bt_total_pnl": 0,
        "compare_total_pnl": 0,
        "comparison_metrics": [],
        "daily_breakdown": [],
        "symbol_breakdown": [],
        "trade_count": 0,
    }
    
    # Validate inputs
    if compare_mode == "historical_replay" and not session_id:
        logger.warning(f"Attribution comparison: session_id required for historical_replay mode, strategy={strategy_id}")
        return {
            **empty_result,
            "message": "历史回放模式需要提供 session_id 参数",
            "error": "session_id is required when compare_mode is 'historical_replay'"
        }
    
    try:
        result = await attribution_service.get_attribution_comparison(
            strategy_id=strategy_id,
            base_mode=base_mode,
            compare_mode=compare_mode,
            session_id=session_id,
            symbol=symbol,
            days=days,
        )
        
        # 处理服务层返回的错误
        if "error" in result and result["error"]:
            logger.warning(f"Attribution comparison error for strategy={strategy_id}: {result['error']}")
            return {
                **empty_result,
                **result,  # 保留原有数据结构
                "message": f"归因对比数据不可用: {result['error']}",
            }
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get attribution comparison for strategy={strategy_id}: {e}", exc_info=True)
        return {
            **empty_result,
            "message": f"归因对比暂不可用: {str(e)}",
            "error": str(e)
        }


@router.get("/attribution/enhanced/{strategy_id}")
async def get_enhanced_attribution(
    strategy_id: str,
    mode: str = Query("paper", pattern="^(backtest|historical_replay|paper)$"),
    session_id: Optional[str] = Query(None, description="Session ID for historical_replay mode"),
    symbol: Optional[str] = Query("BTCUSDT"),
    days: int = Query(7, ge=1, le=30),
):
    """
    获取增强版归因分析，包含新增维度：
    - slippage_impact: 价格滑点造成的损益影响
    - latency_impact: 延迟导致的价格变化影响
    - execution_quality: 执行质量评分 (0-100)
    - timing_diff: 信号产生到成交的时间差（秒）
    """
    import logging
    logger = logging.getLogger(__name__)
    
    # 空数据返回结构（用于降级）
    empty_response = {
        "strategy_id": strategy_id,
        "mode": mode,
        "session_id": session_id,
        "symbol": symbol,
        "summary": {
            "total_slippage": 0,
            "total_delay_cost": 0,
            "total_spread_cost": 0,
            "total_fee": 0,
            "total_execution_diff": 0,
            "trade_count": 0,
        },
        "enhanced_summary": {
            "total_slippage_impact": 0,
            "total_latency_impact": 0,
            "avg_execution_quality": None,
            "avg_timing_diff": None,
        },
        "trades": [],
        "full_attribution": None,
    }
    
    try:
        # Validate inputs for historical_replay mode
        if mode == "historical_replay" and not session_id:
            logger.warning(f"Enhanced attribution: session_id required for historical_replay mode, strategy={strategy_id}")
            return {
                **empty_response,
                "message": "历史回放模式需要提供 session_id 参数",
                "error": "session_id is required when mode is 'historical_replay'"
            }
        
        report = await attribution_service.get_strategy_attribution(
            strategy_id=strategy_id,
            symbol=symbol,
            days=days,
            base_mode="backtest",
            compare_mode=mode,
            replay_session_id=session_id,
        )
        
        # 处理服务层返回的错误
        if report and "error" in report and report["error"]:
            logger.warning(f"Enhanced attribution error for strategy={strategy_id}, mode={mode}: {report['error']}")
            return {
                **empty_response,
                "message": f"归因分析数据不可用: {report['error']}",
                "error": report["error"],
            }
        
        # 检查是否有交易数据
        trades = report.get("trades", report.get("signal_level_details", []))
        if not trades:
            mode_name_map = {"backtest": "回测", "historical_replay": "历史回放", "paper": "模拟盘"}
            mode_display = mode_name_map.get(mode, mode)
            logger.info(f"Enhanced attribution: No trades found for strategy={strategy_id}, mode={mode}, session_id={session_id}")
            return {
                **empty_response,
                "message": f"该策略在{mode_display}模式下暂无交易数据",
            }
        
        # Extract enhanced metrics summary
        global_data = report.get("global_agg", report.get("global", {})) or {}
        enhanced_summary = {
            "total_slippage_impact": global_data.get("total_slippage_impact", 0),
            "total_latency_impact": global_data.get("total_latency_impact", 0),
            "avg_execution_quality": global_data.get("avg_execution_quality"),
            "avg_timing_diff": global_data.get("avg_timing_diff"),
        }
        
        # 构建 summary（兼容前端旧格式）
        summary = {
            "total_slippage": global_data.get("total_slippage_impact", 0),
            "total_delay_cost": global_data.get("total_latency_impact", 0),
            "total_spread_cost": abs(global_data.get("delta_price", 0)),
            "total_fee": abs(global_data.get("delta_fees", 0)),
            "total_execution_diff": global_data.get("delta_total", 0),
            "trade_count": len(trades),
        }
        
        return {
            "strategy_id": strategy_id,
            "mode": mode,
            "session_id": session_id,
            "symbol": symbol,
            "summary": summary,
            "enhanced_summary": enhanced_summary,
            "trades": trades,
            "full_attribution": report,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Enhanced attribution error for strategy={strategy_id}, mode={mode}, session_id={session_id}: {e}", exc_info=True)
        return {
            **empty_response,
            "message": f"归因分析暂不可用: {str(e)}",
            "error": str(e),
        }
