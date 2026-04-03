"""
ClickHouse Service — Time-Series Analytics for K-line Historical Data

Responsibilities:
  - Initialize ClickHouse table (klines) on startup via DDL
  - Bulk-insert K-line records from Binance
  - Query historical K-lines with symbol/interval/time range filters
  - Provide a pandas DataFrame interface for strategy backtest engine

ClickHouse is used as a columnar analytics store for fast aggregation queries
over millions of OHLCV rows that would be slow in PostgreSQL.

Dependency: clickhouse-connect (pip install clickhouse-connect)
Falls back gracefully if ClickHouse is unavailable (returns None / empty list).
"""

import logging
from datetime import datetime
from typing import List, Optional, Dict, Any

import pandas as pd

from app.core.config import settings, no_proxy_env

logger = logging.getLogger(__name__)

# ── DDL for klines table ──────────────────────────────────────────────────────
CREATE_KLINES_SQL = """
CREATE TABLE IF NOT EXISTS klines (
    symbol      LowCardinality(String)   COMMENT 'Trading pair, e.g. BTCUSDT',
    interval    LowCardinality(String)   COMMENT 'Candlestick interval: 1m/5m/1h/1d ...',
    open_time   DateTime64(3, 'UTC')     COMMENT 'Candle open time (milliseconds precision)',
    open        Float64,
    high        Float64,
    low         Float64,
    close       Float64,
    volume      Float64,
    close_time  DateTime64(3, 'UTC')     COMMENT 'Candle close time'
) ENGINE = ReplacingMergeTree()
PARTITION BY toYYYYMM(open_time)
ORDER BY (symbol, interval, open_time)
SETTINGS index_granularity = 8192
"""

# ── Client singleton ──────────────────────────────────────────────────────────
import threading
_client = None
_client_lock = threading.Lock()


def _ch_connect(database: str, **extra):
    """
    Create a clickhouse_connect client while bypassing any HTTP proxy.
    ClickHouse is an internal service — traffic must never go through a proxy.
    Uses no_proxy_env() from app.core.config for consistent proxy management.
    """
    import clickhouse_connect
    with no_proxy_env():
        return clickhouse_connect.get_client(
            host=settings.CLICKHOUSE_HOST,
            port=settings.CLICKHOUSE_PORT,
            database=database,
            username=settings.CLICKHOUSE_USER,
            password=settings.CLICKHOUSE_PASSWORD,
            **extra,
        )


def _ensure_database() -> bool:
    """
    Ensure the target database exists by connecting to 'default' first.
    This handles the case where the ClickHouse container has no init scripts
    and the target database has never been created.
    Returns True if the database is ready, False on any failure.
    """
    try:
        # Connect to built-in 'default' database which always exists
        admin = _ch_connect(database="default", connect_timeout=5)
        admin.command(f"CREATE DATABASE IF NOT EXISTS {settings.CLICKHOUSE_DB}")
        logger.info(f"ClickHouse database '{settings.CLICKHOUSE_DB}' ensured.")
        return True
    except ImportError:
        return False
    except Exception as e:
        logger.warning(f"ClickHouse database ensure failed: {e}")
        return False


def _get_event_loop():
    """
    安全获取事件循环，兼容后台任务执行上下文。
    内部调用统一的 get_safe_event_loop() 实现。
    """
    from app.core.async_utils import get_safe_event_loop
    return get_safe_event_loop()


def _get_client():
    """Lazily initialize and return a ClickHouse HTTP client. Returns None on failure."""
    global _client
    if _client is not None:
        return _client
    try:
        # Ensure target database exists before connecting to it
        _ensure_database()
        _client = _ch_connect(
            database=settings.CLICKHOUSE_DB,
            connect_timeout=5,
            send_receive_timeout=30,
        )
        logger.info(
            f"ClickHouse client connected: {settings.CLICKHOUSE_HOST}:{settings.CLICKHOUSE_PORT}/{settings.CLICKHOUSE_DB}"
        )
        return _client
    except ImportError:
        logger.warning(
            "clickhouse-connect not installed. Run: pip install clickhouse-connect"
        )
        return None
    except Exception as e:
        logger.warning(f"ClickHouse connection failed: {e}")
        return None


class ClickHouseService:
    """
    Async-compatible ClickHouse service (uses sync driver in thread pool via
    asyncio.get_event_loop().run_in_executor so the FastAPI event loop is not blocked).
    """

    # ── Initialization ────────────────────────────────────────────────────────
    def init_tables(self) -> bool:
        """
        Ensure target database exists and create klines table if needed.
        Called at app startup. Safe to call multiple times (idempotent).
        """
        client = _get_client()
        if client is None:
            logger.warning("ClickHouse unavailable — skipping table init")
            return False
        try:
            client.command(CREATE_KLINES_SQL)
            logger.info("ClickHouse klines table verified/created.")
            return True
        except Exception as e:
            logger.error(f"ClickHouse table init failed: {e}")
            return False

    async def async_init_tables(self) -> bool:
        """Async wrapper for table initialization."""
        import asyncio
        loop = _get_event_loop()
        return await loop.run_in_executor(None, self.init_tables)

    # ── Insert K-lines ────────────────────────────────────────────────────────
    def insert_klines_sync(
        self,
        symbol: str,
        interval: str,
        rows: List[Dict[str, Any]],
    ) -> int:
        """
        Bulk insert K-line rows into ClickHouse.

        Each row dict must contain:
            open_time (datetime), open, high, low, close, volume, close_time (datetime)

        Returns the number of rows inserted, or 0 on failure.
        """
        client = _get_client()
        if client is None or not rows:
            return 0
        with _client_lock:
            try:
                data = [
                    [
                        symbol,
                        interval,
                        r["open_time"],
                        float(r["open"]),
                        float(r["high"]),
                        float(r["low"]),
                        float(r["close"]),
                        float(r["volume"]),
                        r["close_time"],
                    ]
                    for r in rows
                ]
                client.insert(
                    "klines",
                    data,
                    column_names=[
                        "symbol", "interval", "open_time",
                        "open", "high", "low", "close", "volume", "close_time",
                    ],
                )
                return len(data)
            except Exception as e:
                logger.warning(f"ClickHouse insert failed ({symbol}/{interval}): {e}")
                return 0

    async def insert_klines(
        self,
        symbol: str,
        interval: str,
        rows: List[Dict[str, Any]],
    ) -> int:
        """Async wrapper for insert_klines_sync."""
        import asyncio
        loop = _get_event_loop()
        return await loop.run_in_executor(
            None, self.insert_klines_sync, symbol, interval, rows
        )

    # ── Query K-lines ─────────────────────────────────────────────────────────
    def query_klines_sync(
        self,
        symbol: str,
        interval: str,
        start: Optional[datetime] = None,
        end: Optional[datetime]   = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        Query K-lines from ClickHouse.

        Returns list of dicts with keys:
            open_time, open, high, low, close, volume, close_time
        """
        client = _get_client()
        if client is None:
            return []
        with _client_lock:
            try:
                conditions = [
                    f"symbol = '{symbol}'",
                    f"interval = '{interval}'",
                ]
                if start:
                    conditions.append(f"open_time >= '{start.strftime('%Y-%m-%d %H:%M:%S')}'")
                if end:
                    conditions.append(f"open_time <= '{end.strftime('%Y-%m-%d %H:%M:%S')}'")

                where = " AND ".join(conditions)
                sql   = f"""
                    SELECT open_time, open, high, low, close, volume, close_time
                    FROM klines
                    WHERE {where}
                    ORDER BY open_time ASC
                    LIMIT {limit}
                    OFFSET {offset}
                """
                result = client.query(sql)
                rows = []
                for row in result.result_rows:
                    rows.append({
                        "open_time":  row[0],
                        "open":       row[1],
                        "high":       row[2],
                        "low":        row[3],
                        "close":      row[4],
                        "volume":     row[5],
                        "close_time": row[6],
                    })
                return rows
            except Exception as e:
                logger.warning(f"ClickHouse query failed ({symbol}/{interval}): {e}")
                return []

    async def query_klines(
        self,
        symbol: str,
        interval: str,
        start: Optional[datetime] = None,
        end: Optional[datetime]   = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Async wrapper for query_klines_sync."""
        import asyncio
        loop = _get_event_loop()
        return await loop.run_in_executor(
            None, self.query_klines_sync, symbol, interval, start, end, limit, offset
        )

    # ── DataFrame interface (for backtest engine) ─────────────────────────────
    async def get_klines_dataframe(
        self,
        symbol: str,
        interval: str,
        start: Optional[datetime] = None,
        end: Optional[datetime]   = None,
        limit: int = 2000,
    ) -> Optional[pd.DataFrame]:
        """
        Return K-lines as a pandas DataFrame with DatetimeIndex.
        Returns None if ClickHouse is unavailable or has insufficient data.
        """
        rows = await self.query_klines(symbol, interval, start, end, limit)
        if len(rows) < 2:
            return None
        df = pd.DataFrame(rows)
        df["open_time"] = pd.to_datetime(df["open_time"])
        df.set_index("open_time", inplace=True)
        df.rename(columns={"close_time": "_close_time"}, inplace=True)
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)
        # Remove duplicate timestamps and ensure ascending order
        # This prevents frontend error: "data must be asc ordered by time"
        df = df[~df.index.duplicated(keep='last')]
        df = df.sort_index()
        return df

    # ── Availability check ────────────────────────────────────────────────────
    async def ping(self) -> bool:
        """Check ClickHouse connectivity."""
        import asyncio
        def _ping():
            client = _get_client()
            if client is None:
                return False
            try:
                with _client_lock:
                    client.command("SELECT 1")
                return True
            except Exception:
                return False
        loop = _get_event_loop()
        return await loop.run_in_executor(None, _ping)

    # ── Count records ─────────────────────────────────────────────────────────
    async def count_klines(self, symbol: str, interval: str) -> int:
        """Return the number of stored K-line rows for a symbol+interval."""
        import asyncio
        def _count():
            client = _get_client()
            if client is None:
                return 0
            try:
                with _client_lock:
                    result = client.query(
                        f"SELECT count() FROM klines WHERE symbol='{symbol}' AND interval='{interval}'"
                    )
                return int(result.result_rows[0][0])
            except Exception:
                return 0
        loop = _get_event_loop()
        return await loop.run_in_executor(None, _count)

    async def get_bar_count(
        self,
        symbol: str,
        interval: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> int:
        """Return the number of K-line bars in a specific time range."""
        import asyncio
        def _count():
            client = _get_client()
            if client is None:
                return 0
            try:
                with _client_lock:
                    conditions = [
                        f"symbol='{symbol}'",
                        f"interval='{interval}'",
                    ]
                    if start_time:
                        conditions.append(f"open_time >= '{start_time.strftime('%Y-%m-%d %H:%M:%S')}'")
                    if end_time:
                        conditions.append(f"open_time <= '{end_time.strftime('%Y-%m-%d %H:%M:%S')}'")
                    
                    cond_str = " AND ".join(conditions)
                    result = client.query(f"SELECT count() FROM klines WHERE {cond_str}")
                    return int(result.result_rows[0][0])
            except Exception as e:
                logger.warning(f"get_bar_count failed ({symbol}/{interval}): {e}")
                return 0
        loop = _get_event_loop()
        return await loop.run_in_executor(None, _count)

    # ── Get date range ────────────────────────────────────────────────────────
    async def get_valid_date_range(self, symbol: str, interval: Optional[str] = None) -> Dict[str, Any]:
        """Return the min/max dates and unique days with data for a symbol and optional interval."""
        import asyncio
        def _get_range():
            client = _get_client()
            if client is None:
                return {"min_date": None, "max_date": None, "valid_dates": []}
            try:
                with _client_lock:
                    # Build condition with optional interval filter
                    conditions = [f"symbol='{symbol}'"]
                    if interval:
                        conditions.append(f"interval='{interval}'")

                    cond_str = " AND ".join(conditions)

                    # Get min/max
                    res_range = client.query(
                        f"SELECT min(open_time), max(open_time) FROM klines WHERE {cond_str}"
                    )
                    min_dt, max_dt = res_range.result_rows[0] if res_range.result_rows else (None, None)

                    # Get unique days
                    res_days = client.query(
                        f"SELECT DISTINCT toDate(open_time) FROM klines WHERE {cond_str} ORDER BY toDate(open_time)"
                    )
                    valid_dates = [str(r[0]) for r in res_days.result_rows]

                return {
                    "min_date": min_dt,
                    "max_date": max_dt,
                    "valid_dates": valid_dates
                }
            except Exception as e:
                logger.error(f"ClickHouse get_valid_date_range failed for {symbol}/{interval}: {e}")
                return {"min_date": None, "max_date": None, "valid_dates": []}
        
        loop = _get_event_loop()
        return await loop.run_in_executor(None, _get_range)


    # ── Get max timestamp ──────────────────────────────────────────────────────
    async def get_max_timestamp(self, symbol: str, interval: str) -> Optional[datetime]:
        """
        Get the maximum open_time timestamp for a given symbol/interval.
        Returns None if no data exists.
        """
        import asyncio

        def _get():
            client = _get_client()
            if client is None:
                return None
            try:
                with _client_lock:
                    result = client.query(
                        f"SELECT max(open_time) FROM klines WHERE symbol='{symbol}' AND interval='{interval}'"
                    )
                    if result.result_rows:
                        val = result.result_rows[0][0]
                        return val if val else None
                return None
            except Exception as e:
                logger.warning(f"get_max_timestamp failed ({symbol}/{interval}): {e}")
                return None

        loop = _get_event_loop()
        return await loop.run_in_executor(None, _get)

    # ── Get data gaps ──────────────────────────────────────────────────────────
    async def get_data_gaps(
        self,
        symbol: str,
        interval: str,
        expected_start: datetime,
        expected_end: datetime,
    ) -> List[Dict[str, Any]]:
        """
        Detect gaps in K-line data for a symbol/interval between expected_start and expected_end.

        Returns a list of gap dicts:
            [{"start": datetime, "end": datetime, "missing_minutes": int}, ...]
        """
        import asyncio

        def _get():
            client = _get_client()
            if client is None:
                return []

            # Interval duration in minutes
            interval_minutes = {
                "1m": 1, "5m": 5, "15m": 15, "30m": 30,
                "1h": 60, "2h": 120, "4h": 240, "6h": 360,
                "8h": 480, "12h": 720, "1d": 1440,
                "3d": 4320, "1w": 10080, "1M": 43200,
            }.get(interval, 1)

            try:
                with _client_lock:
                    # Fetch all timestamps in the expected range
                    rows = client.query(
                        f"""
                        SELECT open_time FROM klines
                        WHERE symbol='{symbol}' AND interval='{interval}'
                          AND open_time >= '{expected_start.strftime('%Y-%m-%d %H:%M:%S')}'
                          AND open_time <= '{expected_end.strftime('%Y-%m-%d %H:%M:%S')}'
                        ORDER BY open_time ASC
                        """
                    ).result_rows

                if not rows:
                    # All data is missing
                    diff = (expected_end - expected_start).total_seconds() / 60
                    return [{
                        "start": expected_start,
                        "end": expected_end,
                        "missing_minutes": int(diff),
                    }]

                gaps = []
                prev_ts = None
                for row in rows:
                    ts = row[0]
                    if prev_ts is not None:
                        diff_minutes = (ts - prev_ts).total_seconds() / 60
                        # Gap detected if diff > interval_minutes * 1.5 (allow 50% tolerance)
                        if diff_minutes > interval_minutes * 1.5:
                            gaps.append({
                                "start": prev_ts,
                                "end": ts,
                                "missing_minutes": int(diff_minutes - interval_minutes),
                            })
                    prev_ts = ts

                return gaps

            except Exception as e:
                logger.warning(f"get_data_gaps failed ({symbol}/{interval}): {e}")
                return []

        loop = _get_event_loop()
        return await loop.run_in_executor(None, _get)

    # ── Get all data ranges (for health check) ─────────────────────────────────
    async def get_all_data_ranges(self) -> List[Dict[str, Any]]:
        """
        Return summary of all stored data: symbol, interval, min_time, max_time, row_count.
        """
        import asyncio

        def _get():
            client = _get_client()
            if client is None:
                return []
            try:
                with _client_lock:
                    result = client.query(
                        """
                        SELECT symbol, interval,
                               min(open_time) AS min_time,
                               max(open_time) AS max_time,
                               count()        AS row_count
                        FROM klines
                        GROUP BY symbol, interval
                        ORDER BY symbol, interval
                        """
                    )
                return [
                    {
                        "symbol": r[0],
                        "interval": r[1],
                        "min_time": r[2],
                        "max_time": r[3],
                        "row_count": r[4],
                    }
                    for r in result.result_rows
                ]
            except Exception as e:
                logger.warning(f"get_all_data_ranges failed: {e}")
                return []

        loop = _get_event_loop()
        return await loop.run_in_executor(None, _get)


# Singleton
clickhouse_service = ClickHouseService()
