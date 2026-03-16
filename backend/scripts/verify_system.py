
import asyncio
import logging
import sys
import os

# Add backend to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from app.core.config import settings
from app.services.database import redis_set, redis_get, check_db_connection, check_redis_connection, init_db
from app.services.binance_service import binance_service
from app.services.paper_trading_service import paper_trading_service
from app.models.db_models import AgentMemory

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def verify_redis_cache():
    logger.info("--- Verifying Redis Cache Integration ---")
    if not await check_redis_connection():
        logger.error("Redis not connected!")
        return

    symbol = "BTCUSDT"
    mock_ticker = {
        "symbol": symbol,
        "price": 99999.99,
        "change_24h": 100.0,
        "change_percent": 0.1,
        "volume": 1000.0,
        "high_24h": 100000.0,
        "low_24h": 99000.0,
        "timestamp": 1700000000
    }
    
    # 1. Set Mock Data in Redis (Simulating IngestionService)
    await redis_set(f"market:{symbol}:ticker", mock_ticker)
    logger.info(f"Set mock ticker in Redis for {symbol}")
    
    # 2. Fetch via BinanceService (Should hit cache)
    ticker = await binance_service.get_ticker(symbol)
    if ticker.price == 99999.99:
        logger.info("✅ BinanceService successfully retrieved price from Redis Cache!")
    else:
        logger.error(f"❌ BinanceService failed to hit cache. Got {ticker.price}")

async def verify_oms_state():
    logger.info("--- Verifying OMS State Machine ---")
    if not await check_db_connection():
        logger.error("DB not connected!")
        return

    # Ensure tables exist
    await init_db()

    symbol = "ETHUSDT"
    price = 2000.0
    
    # 1. Create Limit Order (Expect NEW)
    try:
        order = await paper_trading_service.create_order(
            symbol=symbol,
            side="BUY",
            quantity=1.0,
            price=price,
            order_type="LIMIT"
        )
        if order['status'] == "NEW":
            logger.info(f"✅ Limit Order Created with status: {order['status']}")
        else:
            logger.error(f"❌ Limit Order status mismatch. Got {order['status']}")
            
        # 2. Cancel it to clean up
        await paper_trading_service.cancel_order(order['order_id'])
        logger.info("Order canceled.")
        
    except Exception as e:
        logger.error(f"OMS Test Failed: {e}")

async def main():
    try:
        await verify_redis_cache()
        await verify_oms_state()
    except Exception as e:
        logger.error(f"Verification failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())
