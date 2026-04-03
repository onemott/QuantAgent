"""
Binance Exchange Service
提供 Binance 交易所数据获取功能
"""

import ccxt.async_support as ccxt
import aiohttp
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from app.core.config import settings
from app.models.market_data import TickerData, KlineData, SymbolInfo
import asyncio
import logging

logger = logging.getLogger(__name__)

from app.services.database import redis_get
from app.core.config import get_proxy_url

class BinanceService:
    """Binance 交易所服务类 (Async implementation)"""
    
    def __init__(self):
        """初始化配置"""
        self.config = {
            'enableRateLimit': True,
            'timeout': 30000,  # 30秒超时
            'options': {
                'defaultType': 'spot',
                'adjustForTimeDifference': True,
            }
        }
        
        # Binance requires proxy in restricted regions.
        # We pass the proxy explicitly to ccxt / aiohttp rather than
        # setting global environment variables (which would affect ALL
        # services including internal ones like ClickHouse and Ollama).
        proxy_url = get_proxy_url()
        self._proxy_configured = bool(proxy_url)
        self._proxy_url = proxy_url
        if proxy_url:
            # ccxt uses 'aiohttp_proxy' for async exchanges
            self.config['aiohttp_proxy'] = proxy_url
            logger.info(f"BinanceService: using explicit proxy {proxy_url}")
        
        # Private Exchange (with API Key)
        self.private_config = self.config.copy()
        if settings.BINANCE_API_KEY:
            self.private_config['apiKey'] = settings.BINANCE_API_KEY
        
        if settings.BINANCE_PRIVATE_KEY_PATH:
            try:
                with open(settings.BINANCE_PRIVATE_KEY_PATH, 'rb') as f:
                    private_key_pem = f.read()
                self.private_config['secret'] = private_key_pem.decode('utf-8')
            except Exception as e:
                logger.warning(f"Warning: Could not load private key: {e}")
        
        # 延迟初始化
        self._exchange = None
        self._public_exchange = None
        self._session = None

    async def _ensure_initialized(self):
        """确保 exchange 实例已初始化"""
        if self._public_exchange:
            return

        if self._proxy_configured and not self._session:
            # Use trust_env=False: proxy is already in self.config['proxies'],
            # we do NOT want aiohttp to pick up any other env-based proxy.
            proxy_url = get_proxy_url()
            # Create TCPConnector with family=0 to support both IPv4 and IPv6
            connector = aiohttp.TCPConnector(family=0)
            # Create ClientSession with explicit proxy
            self._session = aiohttp.ClientSession(
                connector=connector,
                trust_env=False,
            )
            # Patch ccxt to use our session
            self.config['session'] = self._session
            self.private_config['session'] = self._session
            logger.info(f"BinanceService: aiohttp session created with explicit proxy {proxy_url}")

        # Create exchange instances with only spot API enabled
        if not self._exchange:
            self._exchange = ccxt.binance(self.private_config)
            self._exchange.options['fetchMarkets'] = ['spot']
            self._exchange.options['defaultType'] = 'spot'

        if not self._public_exchange:
            self._public_exchange = ccxt.binance(self.config)
            self._public_exchange.options['fetchMarkets'] = ['spot']
            self._public_exchange.options['defaultType'] = 'spot'
            
        logger.info(f"Binance exchange initialized (lazy)")

    @property
    def exchange(self):
        if not self._exchange:
             raise RuntimeError("BinanceService not initialized. Call await _ensure_initialized() or use public methods.")
        return self._exchange

    @property
    def public_exchange(self):
        if not self._public_exchange:
             raise RuntimeError("BinanceService not initialized. Call await _ensure_initialized() or use public methods.")
        return self._public_exchange

    def _normalize_symbol(self, symbol: str) -> str:
        """Ensure symbol is in CCXT format (BTC/USDT)."""
        symbol = symbol.upper()
        if "/" in symbol:
             # Handle potentially malformed symbols like BTCUSDT/USDT
             parts = symbol.split("/")
             if len(parts) == 2:
                 base, quote = parts
                 if base.endswith(quote) and len(base) > len(quote):
                     # Fix double quote suffix in base
                     real_base = base[:-len(quote)]
                     return f"{real_base}/{quote}"
             return symbol
             
        for quote in ("USDT", "BTC", "ETH", "BNB", "BUSD", "USDC"):
            if symbol.endswith(quote):
                base = symbol[: -len(quote)]
                return f"{base}/{quote}"
        return symbol

    async def get_ticker(self, symbol: str = "BTC/USDT") -> TickerData:
        """异步获取指定交易对的实时行情数据 (优先从 Redis 读取)"""
        await self._ensure_initialized()
        symbol = self._normalize_symbol(symbol)
        clean_symbol = symbol.replace('/', '')
        
        # 1. Try Redis Cache (MsgPack)
        try:
            cached = await redis_get(f"market:{clean_symbol}:ticker")
            if cached:
                # cached is already a dict (unpacked by redis_get)
                return TickerData(
                    symbol=cached['symbol'],
                    price=float(cached['price']),
                    change_24h=float(cached['change_24h']),
                    change_percent=float(cached['change_percent']),
                    volume=float(cached['volume']),
                    high_24h=float(cached['high_24h']),
                    low_24h=float(cached['low_24h']),
                    timestamp=datetime.fromtimestamp(cached['timestamp'])
                )
        except Exception as e:
            logger.debug(f"Redis ticker miss for {symbol}: {e}")

        # 2. Fallback to CCXT REST API
        try:
            ticker = await self.public_exchange.fetch_ticker(symbol)
            return TickerData(
                symbol=clean_symbol,
                price=float(ticker['last']),
                change_24h=float(ticker['change'] or 0),
                change_percent=float(ticker['percentage'] or 0),
                volume=float(ticker['quoteVolume'] or 0),
                high_24h=float(ticker['high']),
                low_24h=float(ticker['low']),
                timestamp=datetime.fromtimestamp(ticker['timestamp'] / 1000)
            )
        except Exception as e:
            logger.error(f"Failed to fetch ticker for {symbol}: {e}")
            raise Exception(f"Failed to fetch ticker for {symbol}: {str(e)}")

    async def get_klines(
        self, 
        symbol: str = "BTC/USDT", 
        timeframe: str = "1h", 
        limit: int = 100,
        since: Optional[int] = None
    ) -> List[KlineData]:
        """异步获取 K 线历史数据，并后台写入 ClickHouse 缓存。"""
        await self._ensure_initialized()
        symbol = self._normalize_symbol(symbol)
        try:
            # print(f"Fetching klines for {symbol} using proxy: {self.config.get('proxies')}")
            ohlcv = await self.public_exchange.fetch_ohlcv(
                symbol, 
                timeframe=timeframe, 
                limit=min(limit, 1000),
                since=since
            )
            
            klines = []
            for item in ohlcv:
                klines.append(KlineData(
                    timestamp=datetime.fromtimestamp(item[0] / 1000),
                    open=float(item[1]),
                    high=float(item[2]),
                    low=float(item[3]),
                    close=float(item[4]),
                    volume=float(item[5])
                ))
            
            # 后台异步写入 ClickHouse（不阻塞当前调用）
            asyncio.ensure_future(self._persist_klines_to_clickhouse(symbol, timeframe, klines))
            
            return klines
        except Exception as e:
            logger.error(f"Failed to fetch klines for {symbol}: {e}")
            raise Exception(f"Failed to fetch klines for {symbol}: {str(e)}")

    async def _persist_klines_to_clickhouse(
        self,
        symbol: str,
        timeframe: str,
        klines: List[KlineData],
    ) -> None:
        """将 K 线数据异步写入 ClickHouse（fire-and-forget）。"""
        if not klines:
            return
        try:
            from app.services.clickhouse_service import clickhouse_service
            rows = []
            for k in klines:
                rows.append({
                    "open_time":  k.timestamp,
                    "open":       k.open,
                    "high":       k.high,
                    "low":        k.low,
                    "close":      k.close,
                    "volume":     k.volume,
                    "close_time": k.timestamp,  # approximate; real close_time not in KlineData
                })
            symbol_clean = symbol.replace("/", "")
            inserted = await clickhouse_service.insert_klines(symbol_clean, timeframe, rows)
            if inserted:
                logger.debug(f"ClickHouse: inserted {inserted} klines for {symbol_clean}/{timeframe}")
        except Exception as e:
            logger.debug(f"ClickHouse kline persist skipped: {e}")

    async def get_klines_dataframe(
        self,
        symbol: str = "BTC/USDT",
        timeframe: str = "1h",
        limit: int = 100,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """异步获取 K 线数据并转换为 pandas DataFrame
        
        Args:
            symbol: 交易对，如 "BTC/USDT"
            timeframe: K线周期，如 "1h", "1d"
            limit: 获取的K线数量限制
            start: 开始时间（可选），用于时间范围查询
            end: 结束时间（可选），用于时间范围查询
        """
        await self._ensure_initialized()
        symbol = self._normalize_symbol(symbol)
        
        # 如果指定了时间范围，使用 since 参数从 Binance 获取数据
        if start is not None:
            since = int(start.timestamp() * 1000)  # 转换为毫秒时间戳
            ohlcv = await self.public_exchange.fetch_ohlcv(
                symbol, 
                timeframe=timeframe, 
                since=since,
                limit=limit
            )
        else:
            ohlcv = await self.public_exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        
        df = pd.DataFrame(
            ohlcv,
            columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
        )
        
        # 转换时间戳
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        
        # 设置时间戳为索引
        df.set_index('timestamp', inplace=True)
        
        # 转换数值类型
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)
        
        # 如果指定了结束时间，过滤数据
        if end is not None:
            # 将索引和比较值都转换为同一类型（numpy datetime64）
            import numpy as np
            end_np = np.datetime64(end)
            df = df[df.index.values <= end_np]
        
        return df

    async def get_symbols(self) -> List[SymbolInfo]:
        """异步获取所有可用的交易对"""
        await self._ensure_initialized()
        try:
            markets = await self.public_exchange.load_markets()
            symbols = []
            
            for symbol, market in markets.items():
                if market['type'] == 'spot' and market['active']:
                    symbols.append(SymbolInfo(
                        symbol=symbol.replace('/', ''),
                        base=market['base'],
                        quote=market['quote'],
                        exchange='binance'
                    ))
            
            return symbols
        except Exception as e:
            logger.error(f"Failed to fetch symbols: {e}")
            raise Exception(f"Failed to fetch symbols: {str(e)}")

    async def get_price(self, symbol: str = "BTC/USDT") -> float:
        """异步获取指定交易对的当前价格 (优先从 Redis 读取)"""
        await self._ensure_initialized()
        symbol = self._normalize_symbol(symbol)
        clean_symbol = symbol.replace('/', '')
        
        # 1. Try Redis
        try:
            cached = await redis_get(f"market:{clean_symbol}:ticker")
            if cached and 'price' in cached:
                return float(cached['price'])
        except Exception:
            pass
            
        # 2. Fallback
        try:
            ticker = await self.public_exchange.fetch_ticker(symbol)
            return float(ticker['last'])
        except Exception as e:
            logger.error(f"Failed to fetch price for {symbol}: {e}")
            raise Exception(f"Failed to fetch price for {symbol}: {str(e)}")

    async def get_order_book(self, symbol: str = "BTC/USDT", limit: int = 100) -> Dict[str, Any]:
        """异步获取订单簿数据"""
        await self._ensure_initialized()
        symbol = self._normalize_symbol(symbol)
        try:
            order_book = await self.public_exchange.fetch_order_book(symbol, limit=limit)
            return {
                'symbol': symbol.replace('/', ''),
                'bids': order_book['bids'],
                'asks': order_book['asks'],
                'timestamp': datetime.fromtimestamp(order_book['timestamp'] / 1000) if order_book['timestamp'] else datetime.now()
            }
        except Exception as e:
            logger.error(f"Failed to fetch order book for {symbol}: {e}")
            raise Exception(f"Failed to fetch order book for {symbol}: {str(e)}")

    async def get_recent_trades(self, symbol: str = "BTC/USDT", limit: int = 100) -> List[Dict]:
        """异步获取最近成交记录"""
        await self._ensure_initialized()
        symbol = self._normalize_symbol(symbol)
        try:
            trades = await self.public_exchange.fetch_trades(symbol, limit=limit)
            return [
                {
                    'id': trade['id'],
                    'price': float(trade['price']),
                    'amount': float(trade['amount']),
                    'side': trade['side'],
                    'timestamp': datetime.fromtimestamp(trade['timestamp'] / 1000)
                }
                for trade in trades
            ]
        except Exception as e:
            logger.error(f"Failed to fetch trades for {symbol}: {e}")
            raise Exception(f"Failed to fetch trades for {symbol}: {str(e)}")

    async def close(self):
        """关闭连接"""
        if self._exchange:
            await self._exchange.close()
        if self._public_exchange:
            await self._public_exchange.close()
        if self._session:
            await self._session.close()

# 单例实例
binance_service = BinanceService()
