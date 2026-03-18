
import asyncio
import logging
from datetime import datetime, timedelta
from app.services.clickhouse_service import clickhouse_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def insert_mock_1m_data():
    symbol = "BTCUSDT"
    interval = "1m"
    start_time = datetime(2026, 3, 15, 0, 0, 0)
    
    rows = []
    base_price = 60000.0
    for i in range(1440): # 1 day of 1m data
        open_time = start_time + timedelta(minutes=i)
        rows.append({
            "open_time": open_time,
            "open": base_price + i % 10,
            "high": base_price + i % 10 + 5,
            "low": base_price + i % 10 - 5,
            "close": base_price + (i + 1) % 10,
            "volume": 1.0,
            "close_time": open_time + timedelta(seconds=59)
        })
    
    logger.info(f"Inserting {len(rows)} mock 1m bars for {symbol} starting from {start_time}")
    inserted = await clickhouse_service.insert_klines(symbol, interval, rows)
    logger.info(f"Successfully inserted {inserted} bars.")

if __name__ == "__main__":
    asyncio.run(insert_mock_1m_data())
