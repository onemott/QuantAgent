from pydantic import BaseModel
from typing import Optional, Dict, Any, List
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
    interval: Optional[str] = "1m"  # K线周期: 1m, 5m, 15m, 1h, 4h, 1d
    backtest_id: Optional[int] = None
    equity_snapshot_interval: Optional[int] = None  # 权益快照间隔（秒），默认3600（1小时）

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
    elapsed_seconds: Optional[float] = None  # 实际消耗时间(秒)
    error_count: int = 0
    warnings: List[str] = []
    bars_processed: int = 0
    bars_total: int = 0

class ReplayJumpRequest(BaseModel):
    """Request to jump to a specific time in replay"""
    target_timestamp: datetime

class ValidDateRangeResponse(BaseModel):
    """Response containing valid data range for a symbol"""
    symbol: str
    min_date: Optional[datetime] = None
    max_date: Optional[datetime] = None
    valid_dates: list[str] = []


class ReplaySessionDetailResponse(BaseModel):
    """Detailed replay session info for history list"""
    replay_session_id: str
    strategy_id: int
    strategy_type: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    symbol: str
    start_time: datetime
    end_time: datetime
    speed: int
    initial_capital: float
    status: str
    current_timestamp: Optional[datetime] = None
    is_saved: bool = False
    created_at: datetime
    pnl: Optional[float] = None  # 计算后的 PNL
    data_source: Optional[str] = None
    backtest_id: Optional[int] = None
    params_hash: Optional[str] = None
    metrics: Optional[Dict[str, Any]] = {}


class ReplayTradeStatsResponse(BaseModel):
    """Detailed trade statistics for a replay session"""
    replay_session_id: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    max_profit: float = 0.0
    max_loss: float = 0.0
    total_fees: float = 0.0
    final_equity: float = 0.0
    returns_pct: float = 0.0


class SessionSummaryMetrics(BaseModel):
    """Summary metrics for a replay session"""
    total_return: Optional[float] = None
    trade_count: int = 0
    final_equity: Optional[float] = None
    win_rate: Optional[float] = None
    max_drawdown: Optional[float] = None


class ReplaySessionListItem(BaseModel):
    """Replay session item in paginated list"""
    replay_session_id: str
    strategy_id: int
    strategy_type: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    symbol: str
    start_time: datetime
    end_time: datetime
    speed: int
    initial_capital: float
    status: str
    current_timestamp: Optional[datetime] = None
    is_saved: bool = False
    created_at: datetime
    pnl: Optional[float] = None
    data_source: Optional[str] = None
    backtest_id: Optional[int] = None
    params_hash: Optional[str] = None
    metrics: Optional[Dict[str, Any]] = {}
    summary: Optional[SessionSummaryMetrics] = None


class PaginatedReplaySessionsResponse(BaseModel):
    """Paginated response for replay sessions list"""
    sessions: list[ReplaySessionListItem]
    total_count: int
    page: int
    page_size: int
    total_pages: int


class QuickBacktestResponse(BaseModel):
    """Response for quick backtest from replay session"""
    backtest_id: int
    status: str = "completed"
    metrics: Dict[str, Any] = {}
    message: Optional[str] = None


class TimeEstimateRequest(BaseModel):
    """Request for replay time estimation"""
    symbol: str
    interval: str = "1m"
    start_time: datetime
    end_time: datetime
    speed: int = 1
    strategy_type: str = "ma"


class TimeEstimateResponse(BaseModel):
    """Response for replay time estimation"""
    estimated_seconds: float
    bar_count: int
    notes: Optional[str] = None
    breakdown: Optional[Dict[str, Any]] = None


class ReplayTradeMarker(BaseModel):
    """Trade marker for chart display"""
    time: Optional[str] = None  # ISO timestamp, null if not available
    price: float
    side: str  # "BUY" | "SELL"
    quantity: float
    pnl: Optional[float] = None


class ReplayTradesResponse(BaseModel):
    """Response containing trade list with markers for chart"""
    trades: list[ReplayTradeMarker]
    total_count: int


class ReplayEquityCurveResponse(BaseModel):
    """Response containing equity curve data for chart"""
    equity_curve: list[dict]  # [{t: ISO-string, v: float}]
    baseline_curve: list[dict] = []  # Buy-and-hold baseline (if available)
    markers: list[ReplayTradeMarker] = []
    initial_capital: float


class KlineBar(BaseModel):
    """K-line bar data for replay chart"""
    time: str          # ISO timestamp
    open: float
    high: float
    low: float
    close: float
    volume: float


class IndicatorData(BaseModel):
    """Technical indicator data point"""
    time: str
    values: dict       # e.g. {"ma_short": 45000, "ma_long": 44800}


class ReplayKlineResponse(BaseModel):
    """Response containing klines and indicators for replay"""
    klines: list[KlineBar]
    indicators: dict[str, list[IndicatorData]]
    strategy_type: str
    params: dict


class ReplayPositionResponse(BaseModel):
    """Response containing current position info for replay"""
    has_position: bool
    side: str = ""            # "LONG" | "SHORT" | ""
    quantity: float = 0.0
    avg_price: float = 0.0
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0
