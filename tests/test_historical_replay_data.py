
import asyncio
import logging
from datetime import datetime
from app.services.clickhouse_service import clickhouse_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_data_reading_and_sorting():
    symbol = "BTCUSDT"
    # Try 1m as requested by SPEC "分钟级数据"
    interval = "1m"
    logger.info(f"Testing data reading for {symbol} {interval} from 2026-03-15")
    
    start_time = datetime(2026, 3, 15, 0, 0, 0)
    end_time = datetime(2026, 3, 15, 23, 59, 59)
    
    rows = await clickhouse_service.query_klines(
        symbol=symbol,
        interval=interval,
        start=start_time,
        end=end_time,
        limit=2000 
    )
    
    if rows:
        logger.info(f"Successfully read {len(rows)} bars for {interval}.")
        # Verify sorting
        last_time = None
        is_sorted = True
        for i, row in enumerate(rows):
            current_time = row["open_time"]
            if last_time and current_time < last_time:
                logger.error(f"Data is NOT sorted for {interval}! Row {i} has time {current_time}, but previous row had {last_time}")
                is_sorted = False
                break
            last_time = current_time
        
        if is_sorted:
            logger.info(f"Verification PASSED for {interval}: Data is strictly sorted by timestamp.")
        else:
            logger.error(f"Verification FAILED for {interval}: Data is NOT sorted.")
    else:
        logger.warning(f"No {interval} data found for the specified range.")

if __name__ == "__main__":
    asyncio.run(test_data_reading_and_sorting())
