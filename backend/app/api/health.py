from fastapi import APIRouter
from app.services.database import check_db_connection, check_redis_connection, get_redis
from app.core.config import settings
import logging
import time
import asyncio

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/health", tags=["系统监控"], summary="健康检查", description="检查系统各组件状态，包括数据库、Redis、ClickHouse和摄入服务")
async def health_check():
    """
    系统健康检查端点。
    检查关键依赖项的连接状态：PostgreSQL、Redis、ClickHouse、数据摄入服务。
    """
    # 1. PostgreSQL 检查
    db_ok = await check_db_connection()
    
    # 2. Redis 检查与延迟
    redis_ok = False
    redis_latency_ms = -1
    try:
        r = get_redis()
        if r:
            start = time.time()
            await r.ping()
            redis_latency_ms = (time.time() - start) * 1000
            redis_ok = True
    except Exception:
        pass

    # 3. 数据摄入服务状态
    ingestion_status = "unknown"
    ingestion_mode = "unknown"
    try:
        from app.services.ingestion_service import ingestion_service
        if ingestion_service.running:
            if ingestion_service.use_nats and ingestion_service.nc and ingestion_service.nc.is_connected:
                ingestion_status = "connected"
                ingestion_mode = "nats"
            elif not ingestion_service.use_nats and ingestion_service.local_ws_task and not ingestion_service.local_ws_task.done():
                ingestion_status = "connected"
                ingestion_mode = "local_ws"
            else:
                ingestion_status = "disconnected"
                ingestion_mode = "nats" if ingestion_service.use_nats else "local_ws"
        else:
            ingestion_status = "stopped"
    except ImportError:
        pass

    # 4. WebSocket 连接数
    ws_count = 0
    try:
        from app.core.websocket_manager import ws_manager
        ws_count = len(ws_manager._connections)
    except ImportError:
        pass

    # 5. ClickHouse 检查
    clickhouse_ok = False
    try:
        from app.services.clickhouse_service import clickhouse_service
        if await clickhouse_service.ping():
             clickhouse_ok = True
    except ImportError:
        pass
    except Exception:
        pass

    # 总体状态
    status = "healthy"
    if not db_ok or not redis_ok:
        status = "unhealthy"
    elif ingestion_status != "connected":
        status = "degraded"
    
    return {
        "status":    status,
        "service":   settings.APP_NAME,
        "dependencies": {
            "database":   "connected" if db_ok    else "unavailable",
            "redis":      "connected" if redis_ok else "unavailable",
            "clickhouse": "initialized" if clickhouse_ok else "unknown",
            "ingestion":  ingestion_status,
        },
        "metrics": {
            "redis_latency_ms": round(redis_latency_ms, 2),
            "websocket_connections": ws_count,
            "ingestion_mode": ingestion_mode,
        }
    }
