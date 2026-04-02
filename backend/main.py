"""
QuantAgent OS - FastAPI Backend
API Gateway for Quantitative Trading Platform
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
import json
import logging
from typing import Dict, Set

from app.core.config import settings
from app.api.v1.router import api_router
from app.api.health import router as health_router
from app.core.websocket_manager import ws_manager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ── Startup Backfill ───────────────────────────────────────────────────────────

INTERVALS_STARTUP = {
    "1m":  {"days_back": 7,   "ms_delta": 60_000},
    "5m":  {"days_back": 30,  "ms_delta": 300_000},
    "15m": {"days_back": 60,  "ms_delta": 900_000},
    "1h":  {"days_back": 365, "ms_delta": 3_600_000},
    "4h":  {"days_back": 730, "ms_delta": 14_400_000},
    "1d":  {"days_back": 1825, "ms_delta": 86_400_000},
}

BACKFILL_LOCK_KEY = "quantagent:startup_backfill:lock"
BACKFILL_LOCK_TTL = 3600  # 1 hour


async def _acquire_backfill_lock() -> bool:
    """Try to acquire Redis lock. Returns True if we got the lock."""
    try:
        import redis.asyncio as redis
        from app.core.config import settings
        r = redis.from_url(settings.REDIS_URL)
        acquired = await r.set(BACKFILL_LOCK_KEY, "1", ex=BACKFILL_LOCK_TTL, nx=True)
        await r.aclose()
        return bool(acquired)
    except Exception:
        return False


async def _startup_backfill():
    """
    On startup, check data completeness and trigger incremental sync if needed.
    Uses Redis lock to ensure only one instance runs this at a time.
    """
    from app.services.clickhouse_service import clickhouse_service
    from app.services.binance_service import binance_service

    # Try to acquire lock
    if not await _acquire_backfill_lock():
        logger.info("Startup backfill: another instance is running, skipping.")
        return

    logger.info("Startup backfill: checking data completeness...")

    now = datetime.now(timezone.utc)
    stale_threshold = timedelta(hours=1)
    needs_sync = []

    for symbol in settings.SYMBOLS:
        for interval, config in INTERVALS_STARTUP.items():
            max_ts = await clickhouse_service.get_max_timestamp(symbol, interval)
            if max_ts is None:
                # No data at all — needs full backfill
                needs_sync.append((symbol, interval, "full", config["days_back"]))
                logger.info(f"  [{symbol}/{interval}] 无数据，需要全量回填")
            else:
                diff = now - max_ts
                if diff > stale_threshold:
                    needs_sync.append((symbol, interval, "sync", None))
                    logger.info(f"  [{symbol}/{interval}] 数据过期 (max={max_ts}), 需要增量同步")
                else:
                    logger.info(f"  [{symbol}/{interval}] 数据最新 (max={max_ts})")

    if not needs_sync:
        logger.info("Startup backfill: all data is up-to-date.")
        return

    logger.info(f"Startup backfill: syncing {len(needs_sync)} symbol/interval pairs...")

    def symbol_to_binance(sym: str) -> str:
        if '/' in sym:
            return sym
        if sym.endswith('USDT'):
            return f"{sym[:-4]}/USDT"
        return sym

    total_synced = 0
    for symbol, interval, mode, days_back in needs_sync:
        try:
            config = INTERVALS_STARTUP[interval]
            if mode == "full":
                start_dt = now - timedelta(days=days_back)
                start_ms = int(start_dt.timestamp() * 1000)
            else:
                max_ts = await clickhouse_service.get_max_timestamp(symbol, interval)
                start_ms = int(max_ts.timestamp() * 1000) - config["ms_delta"]

            end_ms = int(now.timestamp() * 1000)
            current_ms = start_ms
            count = 0

            while current_ms < end_ms:
                klines = await binance_service.get_klines(
                    symbol=symbol_to_binance(symbol),
                    timeframe=interval,
                    limit=1000,
                    since=current_ms,
                )
                if not klines:
                    break
                rows = [
                    {
                        "open_time":  k.timestamp,
                        "open":       k.open,
                        "high":       k.high,
                        "low":        k.low,
                        "close":      k.close,
                        "volume":     k.volume,
                        "close_time": k.close_time,
                    }
                    for k in klines
                ]
                await clickhouse_service.insert_klines(symbol, interval, rows)
                count += len(klines)
                last_ts = klines[-1].timestamp.timestamp() * 1000
                current_ms = int(last_ts + config["ms_delta"])
                await asyncio.sleep(0.3)

            logger.info(f"  [{symbol}/{interval}] {mode}: synced {count} bars")
            total_synced += count
        except Exception as e:
            logger.warning(f"  [{symbol}/{interval}] backfill failed: {e}")

    logger.info(f"Startup backfill: done. Total {total_synced} bars synced.")


# ─────────────────────────────────────────────────────────────────────────────
# Lifespan
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("QuantAgent API Server starting up...")

    # Run Alembic migrations
    try:
        from app.services.database import get_engine, check_db_connection
        from app.services.alembic_manager import alembic_manager

        db_ok = await check_db_connection()
        if db_ok:
            engine = get_engine()
            await alembic_manager.upgrade_to_head(engine)
            logger.info("Alembic migrations applied — database schema is up to date.")
        else:
            logger.warning("PostgreSQL not available — running without persistence.")
    except Exception as e:
        logger.error(f"Alembic migration failed: {e}")

    # Redis connectivity check (independent of DB)
    try:
        from app.services.database import check_redis_connection
        redis_ok = await check_redis_connection()
        if redis_ok:
            logger.info("Redis connected.")
        else:
            logger.warning("Redis not available - running without cache.")
    except Exception as e:
        logger.error(f"Redis check failed: {e}")

    # Initialize ClickHouse tables and trigger startup backfill
    try:
        from app.services.clickhouse_service import clickhouse_service
        ch_ok = await clickhouse_service.async_init_tables()
        if ch_ok:
            logger.info("ClickHouse klines table verified.")
        else:
            logger.warning("ClickHouse not available — skipping klines table init.")

        # Startup backfill: async, non-blocking
        asyncio.create_task(_startup_backfill())
    except Exception as e:
        logger.error(f"ClickHouse init failed: {e}")

    # Test Binance connectivity
    try:
        from app.services.binance_service import binance_service
        price = await binance_service.get_price("BTC/USDT")
        logger.info(f"Binance OK: BTC/USDT = {price}")
    except Exception as e:
        logger.error(f"Binance connection test failed: {e}")

    # Test LLM
    try:
        from app.services.market_analysis_service import market_analysis_service
        if market_analysis_service.llm:
            logger.info(f"LLM ready: {type(market_analysis_service.llm).__name__}")
        else:
            logger.warning("LLM provider not initialized.")
    except Exception as e:
        logger.error(f"LLM init failed: {e}")

    # Skill 系统初始化
    try:
        from app.skills.initializer import initialize_skill_system
        skill_result = await initialize_skill_system()
        if skill_result:
            logger.info("✅ Skill系统初始化成功")
        else:
            logger.warning("⚠️ Skill系统初始化返回失败状态")
    except Exception as e:
        logger.warning(f"⚠️ Skill系统初始化失败（非关键）: {e}")

    # Start Ingestion Service (NATS or Local WebSocket)
    try:
        from app.services.ingestion_service import ingestion_service
        # Use asyncio.create_task to avoid blocking startup if NATS is slow
        asyncio.create_task(ingestion_service.start(ws_manager))
        logger.info("IngestionService starting (background task)...")
        
        from app.services.trading_worker import trading_worker
        # Use asyncio.create_task to avoid blocking startup if NATS is slow
        asyncio.create_task(trading_worker.start())
        logger.info("TradingWorker starting (background task)...")
        
        # Start Polling Loop as Fallback (in case NATS/WS fails)
        ws_manager.start_price_loop()
        logger.info("WebSocket price polling loop started.")
    except Exception as e:
        logger.error(f"Failed to start services: {e}")

    # Start Scheduler
    try:
        from scheduler import scheduler_service
        scheduler_service.start()
        logger.info("Scheduler started.")
    except Exception as e:
        logger.error(f"Failed to start Scheduler: {e}")

    yield

    # Shutdown
    # ws_manager.stop_price_loop()
    try:
        from app.services.trading_worker import trading_worker
        await trading_worker.stop()
        logger.info("TradingWorker stopped.")
    except Exception as e:
        logger.error(f"Error stopping TradingWorker: {e}")
        
    try:
        from scheduler import scheduler_service
        scheduler_service.stop()
        logger.info("Scheduler stopped.")
    except Exception as e:
        logger.error(f"Error stopping Scheduler: {e}")
        
    try:
        from app.services.ingestion_service import ingestion_service
        await ingestion_service.stop()
        logger.info("IngestionService stopped.")
    except Exception as e:
        logger.error(f"Error stopping IngestionService: {e}")
        
    try:
        from app.services.binance_service import binance_service
        await binance_service.close()
        logger.info("Binance service connections closed.")
    except Exception as e:
        logger.error(f"Error closing Binance service: {e}")
        
    logger.info("QuantAgent API Server shutting down...")


# ─────────────────────────────────────────────────────────────────────────────
# FastAPI App
# ─────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="QuantAgent OS API",
    description="AI-Native Quantitative Trading Platform API",
    version="0.1.0",
    lifespan=lifespan
)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Global exception handler to ensure all errors are returned as JSON.
    This prevents "Unexpected token 'I' in JSON" errors in the frontend.
    """
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal Server Error: {str(exc)}"},
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")
app.include_router(health_router)


@app.get("/")
async def root():
    return {
        "name": "QuantAgent OS API",
        "version": "0.1.0",
        "status": "running",
        "docs": "/docs",
    }


# ─────────────────────────────────────────────────────────────────────────────
# WebSocket Endpoint
# ─────────────────────────────────────────────────────────────────────────────

@app.websocket("/ws/market")
async def market_websocket(websocket: WebSocket):
    """
    Real-time market data WebSocket.
    """
    logger.info(f"WebSocket connection attempt from {websocket.client}")
    try:
        await ws_manager.connect(websocket)
        logger.info(f"WebSocket accepted: {websocket.client}")
    except Exception as e:
        logger.error(f"WebSocket connection failed at accept: {e}")
        return

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            action = msg.get("action", "")
            symbol = msg.get("symbol", "BTCUSDT").upper()

            if action == "subscribe":
                await ws_manager.subscribe(websocket, symbol)
                await websocket.send_json({
                    "type":    "subscribed",
                    "symbol":  symbol,
                    "message": f"Subscribed to {symbol}",
                })
            elif action == "unsubscribe":
                await ws_manager.unsubscribe(websocket, symbol)
                await websocket.send_json({
                    "type":    "unsubscribed",
                    "symbol":  symbol,
                })
            elif action == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await ws_manager.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn
    import sys
    
    # Enable uvloop on Linux/Mac (Production)
    if sys.platform != "win32":
        try:
            import uvloop
            uvloop.install()
            logger.info("uvloop installed.")
        except ImportError:
            logger.warning("uvloop not found, using default asyncio loop.")

    # uvicorn.run(
    #     "main:app",
    #     host=settings.HOST,
    #     port=settings.PORT,
    #     reload=settings.DEBUG,
    #     log_level="info",
    #     ws="websockets",
    # )
    
    # Use config object to ensure ws="websockets" is applied
    config = uvicorn.Config(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="info",
        ws="auto",
        # http="httptools",
    )
    server = uvicorn.Server(config)
    server.run()
