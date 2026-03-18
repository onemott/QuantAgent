"""
Database & Redis Connection Service
Provides async SQLAlchemy session and Redis client for QuantAgent OS.
"""

import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional, Any
import asyncio
import uuid
import time

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import text
import msgpack

from app.core.config import settings

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# PostgreSQL – SQLAlchemy Async Engine
# ─────────────────────────────────────────────────────────────────────────────
_engine = None
_async_session_factory = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            settings.DATABASE_URL,
            echo=False,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
        )
    return _engine


def get_session_factory():
    global _async_session_factory
    if _async_session_factory is None:
        _async_session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _async_session_factory


@asynccontextmanager
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager for database sessions."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI Dependency for database sessions."""
    async with get_db() as session:
        yield session


async def init_db():
    """Create all tables if they don't exist (fallback when init-scripts not used)."""
    from app.models.db_models import Base
    engine = get_engine()
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables verified/created.")
    except Exception as e:
        logger.error(f"Database init failed: {e}")


async def check_db_connection() -> bool:
    """Test database connectivity."""
    try:
        async with get_db() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error(f"DB connection check failed: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Redis – Async Client with MsgPack & Distributed Lock
# ─────────────────────────────────────────────────────────────────────────────
_redis_client = None


def get_redis():
    """Get (lazily initialized) Redis client. Returns None if unavailable."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis.asyncio as aioredis
        # decode_responses=False for msgpack (bytes)
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=False, 
        )
        return _redis_client
    except Exception as e:
        logger.warning(f"Redis client init failed: {e}")
        return None


async def redis_get(key: str) -> Optional[Any]:
    """Get a MsgPack value from Redis. Returns None on miss or error."""
    r = get_redis()
    if r is None:
        return None
    try:
        raw = await r.get(key)
        # raw=False ensures strings are decoded to str, not bytes
        return msgpack.unpackb(raw, raw=False) if raw else None
    except Exception as e:
        logger.warning(f"Redis GET {key} failed: {e}")
        return None


async def redis_set(key: str, value: Any, ttl: int = 5) -> bool:
    """Set a MsgPack value in Redis with TTL (seconds). Returns False on error."""
    r = get_redis()
    if r is None:
        return False
    try:
        packed = msgpack.packb(value, use_bin_type=True)
        await r.set(key, packed, ex=ttl)
        return True
    except Exception as e:
        logger.warning(f"Redis SET {key} failed: {e}")
        return False


async def redis_delete(key: str) -> bool:
    """Delete a Redis key. Returns False on error."""
    r = get_redis()
    if r is None:
        return False
    try:
        await r.delete(key)
        return True
    except Exception as e:
        logger.warning(f"Redis DEL {key} failed: {e}")
        return False


async def check_redis_connection() -> bool:
    """Test Redis connectivity."""
    r = get_redis()
    if r is None:
        return False
    try:
        await r.ping()
        return True
    except Exception as e:
        logger.warning(f"Redis ping failed: {e}")
        return False


class RedisLock:
    """
    Async Distributed Lock based on Redis SET NX.
    Usage:
        async with RedisLock("my_lock_key", expire=10):
            # critical section
            ...
    """
    def __init__(self, key: str, expire: int = 10, retry_delay: float = 0.1, timeout: int = 5):
        self.key = f"lock:{key}"
        self.expire = expire
        self.retry_delay = retry_delay
        self.timeout = timeout
        self.token = str(uuid.uuid4())
        self._redis = get_redis()

    async def __aenter__(self):
        if not self._redis:
            raise RuntimeError("Redis is not available for locking")
        
        start_time = time.time()
        while True:
            # Try to acquire lock
            acquired = await self._redis.set(
                self.key, 
                self.token, 
                ex=self.expire, 
                nx=True
            )
            if acquired:
                return self
            
            # Check timeout
            if time.time() - start_time > self.timeout:
                raise TimeoutError(f"Could not acquire lock for {self.key} within {self.timeout}s")
            
            await asyncio.sleep(self.retry_delay)

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if not self._redis:
            return
        
        # Release lock only if we own it (check token)
        # Using Lua script for atomicity
        script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        try:
            await self._redis.eval(script, 1, self.key, self.token)
        except Exception as e:
            logger.warning(f"Error releasing lock {self.key}: {e}")
