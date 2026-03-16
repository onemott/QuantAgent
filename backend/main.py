"""
QuantAgent OS - FastAPI Backend
API Gateway for Quantitative Trading Platform
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
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


# ─────────────────────────────────────────────────────────────────────────────
# Lifespan
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("QuantAgent API Server starting up...")

    # Initialize database tables
    try:
        from app.services.database import init_db, check_db_connection, check_redis_connection
        db_ok = await check_db_connection()
        if db_ok:
            await init_db()
            logger.info("PostgreSQL connected and tables verified.")
        else:
            logger.warning("PostgreSQL not available - running without persistence.")

        redis_ok = await check_redis_connection()
        if redis_ok:
            logger.info("Redis connected.")
        else:
            logger.warning("Redis not available - running without cache.")
    except Exception as e:
        logger.error(f"Database/Redis init failed: {e}")

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

    # Start Ingestion Service (NATS or Local WebSocket)
    try:
        from app.services.ingestion_service import ingestion_service
        await ingestion_service.start(ws_manager)
        logger.info("IngestionService started.")
        
        from app.services.trading_worker import trading_worker
        await trading_worker.start()
        logger.info("TradingWorker started.")
        
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
