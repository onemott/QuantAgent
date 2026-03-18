from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime
from enum import Enum

class TradeSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

class OrderType(str, Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"

class OrderStatus(str, Enum):
    NEW = "NEW"
    PENDING = "PENDING"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"

class BarData(BaseModel):
    """K-line data model"""
    symbol: str
    datetime: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    interval: str

class TickData(BaseModel):
    """Tick data model"""
    symbol: str
    datetime: datetime
    last_price: float
    bid_price: float
    ask_price: float
    bid_volume: float
    ask_volume: float

class OrderRequest(BaseModel):
    """Order request sent by strategy"""
    symbol: str
    side: TradeSide
    quantity: float
    price: Optional[float] = None
    order_type: OrderType = OrderType.MARKET
    strategy_id: str
    benchmark_price: Optional[float] = None
    client_order_id: Optional[str] = None
    remark: Optional[str] = None

class OrderResult(BaseModel):
    """Order result returned by execution router"""
    order_id: str
    client_order_id: Optional[str] = None
    symbol: str
    status: OrderStatus
    filled_quantity: float = 0.0
    filled_price: float = 0.0
    fee: float = 0.0
    pnl: Optional[float] = None
    timestamp: datetime
    error_msg: Optional[str] = None

class ReplayCreateRequest(BaseModel):
    """Request to create a historical replay session"""
    strategy_id: int
    symbol: str
    start_time: datetime
    end_time: datetime
    speed: int # (1, 10, 60, 100)
    initial_capital: float
    strategy_type: Optional[str] = "ma"
    params: Optional[Dict[str, Any]] = None

class ReplaySessionResponse(BaseModel):
    """Response containing replay session info"""
    replay_session_id: str
    status: str
    message: Optional[str] = None

class ReplayStatusResponse(BaseModel):
    """Detailed status of a replay session"""
    replay_session_id: str
    status: str
    current_simulated_time: Optional[datetime] = None
    progress: float = 0.0
    pnl: float = 0.0

class ReplayJumpRequest(BaseModel):
    """Request to jump to a specific time in replay"""
    target_timestamp: datetime

class ValidDateRangeResponse(BaseModel):
    """Response containing valid data range for a symbol"""
    symbol: str
    min_date: Optional[datetime] = None
    max_date: Optional[datetime] = None
    valid_dates: list[str] = []
