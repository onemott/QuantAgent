"""
Market Data Models
"""

from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


class TickerData(BaseModel):
    """Ticker/Price data model"""
    symbol: str
    price: float
    change_24h: float
    change_percent: float
    volume: float
    high_24h: float
    low_24h: float
    timestamp: datetime


class KlineData(BaseModel):
    """Kline/Candlestick data model"""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: Optional[float] = None
    trades: Optional[int] = None


class KlineResponse(BaseModel):
    """Kline response model"""
    symbol: str
    interval: str
    data: List[KlineData]
    source: str


class SymbolInfo(BaseModel):
    """Trading symbol information"""
    symbol: str
    base: str
    quote: str
    exchange: str


class MarketOverview(BaseModel):
    """Market overview data from CoinGecko"""
    id: str
    symbol: str
    name: str
    current_price: float
    market_cap: Optional[float] = None
    market_cap_rank: Optional[int] = None
    price_change_24h: Optional[float] = None
    price_change_percentage_24h: Optional[float] = None
    total_volume: Optional[float] = None
    last_updated: Optional[datetime] = None


class PriceComparison(BaseModel):
    """Price comparison between exchanges"""
    symbol: str
    binance_price: Optional[float] = None
    coingecko_price: Optional[float] = None
    price_diff: Optional[float] = None
    price_diff_percent: Optional[float] = None
    timestamp: datetime
