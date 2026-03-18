
import asyncio
import logging
from app.services.clickhouse_service import clickhouse_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def check_data_availability():
    symbols = ["BTCUSDT", "ETHUSDT"]
    for symbol in symbols:
        result = await clickhouse_service.get_valid_date_range(symbol)
        logger.info(f"Availability for {symbol}: {result}")

if __name__ == "__main__":
    asyncio.run(check_data_availability())
