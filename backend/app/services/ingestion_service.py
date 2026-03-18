"""
Market Data Ingestion Service
Connects to NATS (preferred) or Binance WebSocket (fallback), consumes market data, and updates Redis/internal state.
"""

import asyncio
import json
import logging
import nats
from nats.errors import ConnectionClosedError, TimeoutError, NoServersError
from typing import Optional, Dict
import aiohttp

from app.core.config import settings, get_proxy_url
from app.services.database import redis_set
from app.services.clickhouse_service import clickhouse_service
from datetime import datetime

logger = logging.getLogger(__name__)

class IngestionService:
    def __init__(self):
        self.nc = None
        self.running = False
        self.ws_manager = None
        self.local_ws_task = None
        self.use_nats = True
        self.last_kline_ts = {} # Map[symbol, timestamp_seconds]

    async def start(self, ws_manager=None):
        """Start NATS consumer or fallback to local WebSocket."""
        if self.running:
            return
            
        self.ws_manager = ws_manager
        self.running = True

        # Try NATS first
        try:
            logger.info(f"Connecting to NATS: {settings.NATS_URL} ...")
            self.nc = await nats.connect(
                settings.NATS_URL,
                name="quantagent-backend-ingestion",
                reconnect_time_wait=2,
                max_reconnect_attempts=2, # Fail fast to switch to fallback
                connect_timeout=2
            )
            logger.info(f"NATS connected: {settings.NATS_URL}")

            # Subscribe to ticker updates
            await self.nc.subscribe("market.*.ticker", cb=self._handle_ticker)
            logger.info("Subscribed to market.*.ticker")

            # Subscribe to kline updates
            await self.nc.subscribe("market.*.kline", cb=self._handle_kline)
            logger.info("Subscribed to market.*.kline")

            self.use_nats = True

        except (NoServersError, TimeoutError, OSError, Exception) as e:
            logger.warning(f"NATS connection failed ({e}). Switching to local Binance WebSocket.")
            self.use_nats = False
            self.local_ws_task = asyncio.create_task(self._start_local_stream())

    async def stop(self):
        """Stop consumer."""
        self.running = False
        if self.nc:
            try:
                await self.nc.close()
            except Exception:
                pass
            logger.info("NATS connection closed.")
        
        if self.local_ws_task:
            self.local_ws_task.cancel()
            try:
                await self.local_ws_task
            except asyncio.CancelledError:
                pass
            logger.info("Local WebSocket stopped.")

    async def _handle_ticker(self, msg):
        """Handle ticker message from NATS."""
        try:
            subject = msg.subject
            # Subject: market.{SYMBOL}.ticker
            parts = subject.split(".")
            if len(parts) < 3:
                return
            symbol = parts[1]
            
            data = json.loads(msg.data.decode())
            
            # Save to Redis
            redis_key = f"market:{symbol}:ticker"
            await redis_set(redis_key, data, ttl=10)
            
            # Push to WebSocket manager
            if self.ws_manager:
                payload = data.copy()
                payload["type"] = "ticker"
                payload["symbol"] = symbol
                await self.ws_manager.broadcast_ticker(symbol, payload)
            
        except Exception as e:
            logger.error(f"Error handling ticker msg: {e}")

    async def _handle_kline(self, msg):
        """Handle kline message from NATS."""
        try:
            subject = msg.subject
            parts = subject.split(".")
            if len(parts) < 3:
                return
            symbol = parts[1]
            
            data = json.loads(msg.data.decode())
            
            # Save to Redis (latest kline)
            redis_key = f"market:{symbol}:kline:latest"
            await redis_set(redis_key, data, ttl=60)
            
            # Persist to ClickHouse if closed
            if data.get('closed'):
                await self._persist_kline(symbol, data.get('interval', '1m'), data)
            
        except Exception as e:
            logger.error(f"Error handling kline msg: {e}")

    async def _persist_kline(self, symbol: str, interval: str, kline_data: Dict):
        """Persist closed kline to ClickHouse."""
        try:
            # kline_data expects: open_time(ms), close_time(ms), open, high, low, close, volume
            open_time = datetime.fromtimestamp(kline_data['open_time'] / 1000)
            close_time = datetime.fromtimestamp(kline_data['close_time'] / 1000)
            
            row = {
                "open_time": open_time,
                "open": float(kline_data['open']),
                "high": float(kline_data['high']),
                "low": float(kline_data['low']),
                "close": float(kline_data['close']),
                "volume": float(kline_data['volume']),
                "close_time": close_time
            }
            
            await clickhouse_service.insert_klines(symbol, interval, [row])
            logger.debug(f"Persisted kline for {symbol} to ClickHouse")
        except Exception as e:
            logger.error(f"Failed to persist kline for {symbol}: {e}")

    async def _start_local_stream(self):
        """Connect to Binance WebSocket directly (Fallback) with Exponential Backoff."""
        base_url = "wss://stream.binance.com:9443/stream?streams="
        
        # 支持多周期采集: 1m, 5m, 15m, 1h, 4h
        INTERVALS = ["1m", "5m", "15m", "1h", "4h"]
        
        # Construct streams: <symbol>@miniTicker / <symbol>@kline_<interval>
        streams = []
        for s in settings.SYMBOLS:
            symbol = s.lower()
            streams.append(f"{symbol}@miniTicker")
            for interval in INTERVALS:
                streams.append(f"{symbol}@kline_{interval}")
        
        url = base_url + "/".join(streams)
        proxy_url = get_proxy_url()
        
        logger.info(f"Connecting to Binance WS (Fallback): {url[:50]}... (Proxy: {proxy_url})")
        
        retry_delay = 1
        max_delay = 60

        while self.running:
            try:
                # Use aiohttp for better proxy support
                # Note: verify_ssl=False might be needed for some proxies, but generally default is safer
                connector = aiohttp.TCPConnector(ssl=False)
                async with aiohttp.ClientSession(connector=connector) as session:
                    async with session.ws_connect(url, proxy=proxy_url) as ws:
                        logger.info("Binance WS connected.")
                        retry_delay = 1 # Reset on successful connection
                        
                        while self.running:
                            try:
                                msg = await ws.receive()
                                
                                if msg.type == aiohttp.WSMsgType.TEXT:
                                    data = json.loads(msg.data)
                                    # data: {"stream": "...", "data": {...}}
                                    stream = data.get("stream", "")
                                    payload = data.get("data", {})
                                    
                                    if "miniTicker" in stream:
                                        await self._handle_local_ticker(payload)
                                    elif "kline" in stream:
                                        await self._handle_local_kline(payload)
                                        
                                elif msg.type == aiohttp.WSMsgType.CLOSED:
                                    logger.warning("Binance WS connection closed")
                                    break
                                elif msg.type == aiohttp.WSMsgType.ERROR:
                                    logger.error("Binance WS connection error")
                                    break
                                    
                            except Exception as e:
                                logger.error(f"Error processing WS message: {e}")
                                break
                                
            except Exception as e:
                logger.error(f"Binance WS connection error: {e}")
                
            if self.running:
                logger.info(f"Reconnecting in {retry_delay}s...")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_delay) # Exponential backoff

    async def _handle_local_ticker(self, data: Dict):
        """Handle local miniTicker data."""
        # Payload: {"s": "BNBBTC", "c": "0.0025", ...}
        symbol = data['s']
        price = float(data['c'])
        open_price = float(data['o'])
        
        # Normalize to our TickerData format
        ticker = {
            "symbol": symbol,
            "price": price,
            "change_24h": price - open_price, 
            "change_percent": (price - open_price) / open_price * 100 if open_price else 0,
            "volume": float(data['v']), # Base volume
            "high_24h": float(data['h']),
            "low_24h": float(data['l']),
            "timestamp": data['E'] / 1000 # Unix timestamp in seconds
        }
        
        redis_key = f"market:{symbol}:ticker"
        await redis_set(redis_key, ticker, ttl=10)
        
        if self.ws_manager:
            payload = ticker.copy()
            payload["type"] = "ticker"
            await self.ws_manager.broadcast_ticker(symbol, payload)

    async def _handle_local_kline(self, data: Dict):
        """Handle local kline data (support multi-interval)."""
        # Payload: {"k": {...}}
        k = data['k']
        symbol = k['s']
        interval = k['i']  # Binance provides interval in kline data
        
        # Normalize
        kline = {
            "timestamp": k['t'] / 1000,
            "open": float(k['o']),
            "high": float(k['h']),
            "low": float(k['l']),
            "close": float(k['c']),
            "volume": float(k['v']),
            "closed": k['x']
        }
        
        # Gap Recovery (Simple 1m check)
        current_ts = kline['timestamp']
        last_ts = self.last_kline_ts.get(symbol)
        
        if last_ts and (current_ts - last_ts > 65): # > 60s + 5s buffer
            logger.warning(f"Gap detected for {symbol}: Last {last_ts}, Curr {current_ts}. Triggering recovery...")
            asyncio.create_task(self._recover_gap(symbol, last_ts, current_ts))
            
        self.last_kline_ts[symbol] = current_ts
        
        redis_key = f"market:{symbol}:kline:{interval}:latest"
        await redis_set(redis_key, kline, ttl=60)

        # If closed, persist to ClickHouse
        if k['x']:
            kline_data = {
                "open_time": k['t'],
                "close_time": k['T'],
                "open": k['o'],
                "high": k['h'],
                "low": k['l'],
                "close": k['c'],
                "volume": k['v']
            }
            # Use interval from Binance kline data
            await self._persist_kline(symbol, interval, kline_data)

    async def _recover_gap(self, symbol: str, start_ts: float, end_ts: float):
        """Recover missing klines via REST API."""
        try:
            from app.services.binance_service import binance_service
            # Convert to ms
            since = int((start_ts + 60) * 1000)
            # Calculate limit
            duration = end_ts - start_ts
            limit = int(duration / 60) - 1
            
            if limit > 0:
                logger.info(f"Recovering {limit} missing klines for {symbol}...")
                # This call will automatically persist to ClickHouse via binance_service
                await binance_service.get_klines(symbol, "1m", limit=limit, since=since)
        except Exception as e:
            logger.error(f"Gap recovery failed for {symbol}: {e}")

# Singleton instance
ingestion_service = IngestionService()
