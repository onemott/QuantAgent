"""
补历史数据脚本
从 Binance 获取指定时间段的 K 线数据并写入 ClickHouse
"""
import asyncio
import logging
from datetime import datetime, timezone
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from app.services.binance_service import binance_service
from app.services.clickhouse_service import clickhouse_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def backfill_klines():
    """
    补充 3-12 ~ 3-14 的 1分钟 K 线数据
    """
    symbol = "BTC/USDT"
    timeframe = "1m"
    
    # 3月12日 00:00:00 UTC 到 3月14日 00:00:00 UTC
    start_time = datetime(2026, 3, 12, 0, 0, 0, tzinfo=timezone.utc)
    end_time = datetime(2026, 3, 14, 0, 0, 0, tzinfo=timezone.utc)
    
    # 转换为毫秒时间戳
    since_ms = int(start_time.timestamp() * 1000)
    
    logger.info(f"开始补数据: {symbol} {timeframe}")
    logger.info(f"时间范围: {start_time} ~ {end_time}")
    
    # Binance 单次最多返回 1000 条，这里分段获取
    batch_size = 1000
    current_since = since_ms
    total_fetched = 0
    batch = 0
    
    while True:
        batch += 1
        logger.info(f"获取第 {batch} 批数据...")
        
        klines = await binance_service.get_klines(
            symbol=symbol,
            timeframe=timeframe,
            limit=batch_size,
            since=current_since
        )
        
        if not klines:
            logger.info("没有更多数据了")
            break
        
        total_fetched += len(klines)
        
        # 获取最后一条的时间作为下一次查询的起点
        last_ts = klines[-1].timestamp.timestamp() * 1000
        current_since = int(last_ts + 60000)  # 加1分钟
        
        # 检查是否超出结束时间
        last_dt = datetime.fromtimestamp(last_ts / 1000, tz=timezone.utc)
        if last_dt >= end_time:
            logger.info(f"已达到结束时间: {last_dt}")
            break
        
        # 控制请求频率，避免被限流
        await asyncio.sleep(0.5)
    
    logger.info(f"补数据完成！共获取 {total_fetched} 条 K 线")
    
    # 验证数据
    result = await clickhouse_service.get_valid_date_range("BTCUSDT")
    logger.info(f"当前数据范围: {result}")

if __name__ == "__main__":
    asyncio.run(backfill_klines())
