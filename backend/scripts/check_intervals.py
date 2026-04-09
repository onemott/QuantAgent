
import asyncio
import logging
from app.services.clickhouse_service import clickhouse_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def check_intervals():
    symbol = "BTCUSDT"
    client = clickhouse_service._get_client()
    if client is None:
        logger.error("ClickHouse client not available")
        return
    
    sql = f"SELECT DISTINCT interval FROM klines WHERE symbol = '{symbol}' AND toDate(open_time) = '2026-03-15'"
    result = client.query(sql)
    intervals = [r[0] for r in result.result_rows]
    logger.info(f"Available intervals for {symbol} on 2026-03-15: {intervals}")

if __name__ == "__main__":
    asyncio.run(check_intervals())
