"""
SQLAlchemy ORM Models for QuantAgent OS
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Column, Integer, String, Numeric, DateTime, Text,
    CheckConstraint, Index, Boolean, Float
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector

Base = declarative_base()


class PaperAccount(Base):
    """Virtual trading account - always id=1"""
    __tablename__ = "paper_account"

    id          = Column(Integer, primary_key=True, default=1)
    total_usdt  = Column(Numeric(20, 8), nullable=False, default=100000.0)
    updated_at  = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PaperPosition(Base):
    """Current open positions (one row per symbol/session)"""
    __tablename__ = "paper_positions"
    __table_args__ = (
        Index("idx_paper_positions_session", "session_id"),
    )

    id          = Column(Integer, primary_key=True, autoincrement=True)
    symbol      = Column(String(20), nullable=False)
    session_id  = Column(String(50), nullable=True)   # Added for isolation
    strategy_id = Column(String(30), nullable=True)   # Added for attribution
    quantity    = Column(Numeric(20, 8), nullable=False, default=0)
    avg_price   = Column(Numeric(20, 8), nullable=False, default=0)
    leverage    = Column(Integer, nullable=False, default=1)
    liquidation_price = Column(Numeric(20, 8), nullable=True)
    updated_at  = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PaperTrade(Base):
    """Order / trade history"""
    __tablename__ = "paper_trades"
    __table_args__ = (
        CheckConstraint("side IN ('BUY', 'SELL')", name="ck_paper_trades_side"),
        Index("idx_paper_trades_symbol",  "symbol"),
        Index("idx_paper_trades_created", "created_at"),
        Index("idx_paper_trades_client_order_id", "client_order_id", unique=True),
    )

    id              = Column(Integer, primary_key=True, autoincrement=True)
    strategy_id     = Column(String(30), nullable=True)   # Added for attribution
    client_order_id = Column(String(50), nullable=True)   # Client-provided order ID for idempotency
    symbol          = Column(String(20), nullable=False)
    side            = Column(String(4),  nullable=False)
    order_type      = Column(String(10), nullable=False, default="MARKET")
    quantity        = Column(Numeric(20, 8), nullable=False)
    price           = Column(Numeric(20, 8), nullable=False)
    benchmark_price = Column(Numeric(20, 8), nullable=True)
    fee             = Column(Numeric(20, 8), nullable=False, default=0)
    funding_fee     = Column(Numeric(20, 8), nullable=False, default=0)
    pnl             = Column(Numeric(20, 8), nullable=True)
    status          = Column(String(10), nullable=False, default="FILLED")
    mode            = Column(String(20), nullable=False, default="paper") # paper | backtest | historical_replay
    session_id      = Column(String(50), nullable=True) # For historical_replay session_id
    created_at      = Column(DateTime(timezone=True), server_default=func.now())


class BacktestResult(Base):
    """Stored backtest run results"""
    __tablename__ = "backtest_results"
    __table_args__ = (
        Index("idx_backtest_created",  "created_at"),
        Index("idx_backtest_strategy", "strategy_type", "symbol"),
    )

    id              = Column(Integer, primary_key=True, autoincrement=True)
    strategy_type   = Column(String(20), nullable=False)   # ma | rsi | boll | macd | ema_triple | atr_trend
    symbol          = Column(String(20), nullable=False)
    interval        = Column(String(5),  nullable=False)
    params          = Column(JSONB, nullable=False, default={})
    metrics         = Column(JSONB, nullable=False, default={})
    equity_curve    = Column(JSONB, nullable=False, default=[])
    trades_summary  = Column(JSONB, nullable=False, default=[])
    created_at      = Column(DateTime(timezone=True), server_default=func.now())


class RiskEvent(Base):
    """Risk control event log — records every triggered or passed rule check"""
    __tablename__ = "risk_events"
    __table_args__ = (
        Index("idx_risk_events_symbol",  "symbol"),
        Index("idx_risk_events_created", "created_at"),
        Index("idx_risk_events_rule",    "rule"),
    )

    id         = Column(Integer, primary_key=True, autoincrement=True)
    symbol     = Column(String(20), nullable=False)
    rule       = Column(String(50), nullable=False)   # MAX_SINGLE_POSITION | DRAWDOWN_HALT | DAILY_LOSS_HALT
    triggered  = Column(Boolean, nullable=False, default=True)
    detail     = Column(JSONB, nullable=False, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AgentMemory(Base):
    """Agent short-term memory — stores recent analysis summaries per agent+symbol"""
    __tablename__ = "agent_memories"
    __table_args__ = (
        Index("idx_agent_memories_agent_symbol", "agent_type", "symbol"),
        Index("idx_agent_memories_created",      "created_at"),
    )

    id         = Column(Integer, primary_key=True, autoincrement=True)
    agent_type = Column(String(30), nullable=False)   # trend | mean_reversion | risk
    symbol     = Column(String(20), nullable=False)
    summary    = Column(Text, nullable=False)
    
    # Enhanced Fields for RAG & RL
    reasoning_summary = Column(Text, nullable=True)
    signal     = Column(String(20), nullable=True)    # BUY | SELL | WAIT | LONG_REVERSAL | ...
    action     = Column(String(20), nullable=True)    # Actual action taken: BUY / SELL / HOLD
    confidence = Column(Float, nullable=True)          # 0.0 ~ 1.0
    entry_price = Column(Float, nullable=True)         # Price at the time of analysis
    
    # Vector Embedding (1536 dim for OpenAI text-embedding-3-small)
    market_state_embedding = Column(Vector(1536), nullable=True) 
    
    outcome_pnl = Column(Float, nullable=True)         # PnL realized after N periods
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class OptimizationResult(Base):
    """Strategy parameter grid-search optimization results"""
    __tablename__ = "optimization_results"
    __table_args__ = (
        Index("idx_optim_strategy_symbol", "strategy_type", "symbol"),
        Index("idx_optim_created",         "created_at"),
    )

    id            = Column(Integer, primary_key=True, autoincrement=True)
    strategy_type = Column(String(20), nullable=False)
    symbol        = Column(String(20), nullable=False)
    interval      = Column(String(5),  nullable=False)
    params_grid   = Column(JSONB, nullable=False, default={})   # full grid results [{params, sharpe, ...}]
    best_params   = Column(JSONB, nullable=False, default={})   # params with best sharpe
    best_sharpe   = Column(Float, nullable=True)
    best_return   = Column(Float, nullable=True)
    total_combos  = Column(Integer, nullable=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())


class TradePair(Base):
    """Trade pair - links entry and exit trades for P&L tracking"""
    __tablename__ = "trade_pairs"
    __table_args__ = (
        Index("idx_trade_pairs_pair",   "pair_id"),
        Index("idx_trade_pairs_symbol", "symbol"),
        Index("idx_trade_pairs_status", "status"),
    )

    id              = Column(Integer, primary_key=True, autoincrement=True)
    pair_id         = Column(String(36), nullable=False)      # UUID
    symbol          = Column(String(20), nullable=False)
    strategy_id     = Column(String(30), nullable=True)   # Added for attribution

    # Linked trade IDs
    entry_trade_id  = Column(Integer, nullable=False)
    exit_trade_id   = Column(Integer, nullable=True)

    # Pair info
    entry_time      = Column(DateTime(timezone=True), nullable=False)
    exit_time       = Column(DateTime(timezone=True), nullable=True)

    entry_price     = Column(Numeric(20, 8), nullable=False)
    exit_price      = Column(Numeric(20, 8), nullable=True)

    quantity        = Column(Numeric(20, 8), nullable=False)
    side            = Column(String(5), nullable=False)        # LONG or SHORT

    # Holding costs (fees + funding)
    holding_costs   = Column(Numeric(20, 8), nullable=False, default=0)

    # Pair status
    status          = Column(String(10), nullable=False, default="OPEN")  # OPEN | CLOSED
    pnl             = Column(Numeric(20, 8), nullable=True)
    pnl_pct         = Column(Numeric(10, 4), nullable=True)

    # Holding duration (hours)
    holding_hours   = Column(Numeric(10, 2), nullable=True)

    created_at      = Column(DateTime(timezone=True), server_default=func.now())


class EquitySnapshot(Base):
    """Periodic equity curve snapshot (hourly)"""
    __tablename__ = "equity_snapshots"
    __table_args__ = (
        Index("idx_equity_timestamp", "timestamp"),
    )

    id              = Column(Integer, primary_key=True, autoincrement=True)
    timestamp       = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    total_equity    = Column(Numeric(20, 8), nullable=False)
    cash_balance    = Column(Numeric(20, 8), nullable=False)
    position_value  = Column(Numeric(20, 8), nullable=False, default=0)
    daily_pnl       = Column(Numeric(20, 8), nullable=True, default=0)
    daily_return    = Column(Numeric(10, 6), nullable=True, default=0)
    drawdown        = Column(Numeric(10, 6), nullable=True, default=0)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())


class PerformanceMetric(Base):
    """Aggregated performance metrics over a time period"""
    __tablename__ = "performance_metrics"
    __table_args__ = (
        Index("idx_perf_period", "period"),
    )

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    period              = Column(String(20), nullable=False)   # daily | weekly | monthly | all_time
    start_date          = Column(DateTime(timezone=True), nullable=False)
    end_date            = Column(DateTime(timezone=True), nullable=False)

    # Basic metrics
    initial_equity      = Column(Numeric(20, 8), nullable=False)
    final_equity        = Column(Numeric(20, 8), nullable=False)
    total_return        = Column(Numeric(10, 4), nullable=False, default=0)
    total_trades        = Column(Integer, nullable=False, default=0)
    winning_trades      = Column(Integer, nullable=False, default=0)
    losing_trades       = Column(Integer, nullable=False, default=0)

    # Risk metrics
    max_drawdown        = Column(Numeric(10, 4), nullable=False, default=0)
    max_drawdown_pct    = Column(Numeric(10, 4), nullable=False, default=0)
    volatility          = Column(Numeric(10, 4), nullable=False, default=0)

    # Return metrics
    annualized_return   = Column(Numeric(10, 4), nullable=False, default=0)
    sharpe_ratio        = Column(Numeric(10, 4), nullable=True)
    sortino_ratio       = Column(Numeric(10, 4), nullable=True)
    calmar_ratio        = Column(Numeric(10, 4), nullable=True)

    # Trade metrics
    win_rate            = Column(Numeric(10, 4), nullable=False, default=0)
    profit_factor       = Column(Numeric(10, 4), nullable=True)
    avg_holding_hours   = Column(Numeric(10, 2), nullable=True)
    max_consecutive_wins   = Column(Integer, default=0)
    max_consecutive_losses = Column(Integer, default=0)

    created_at          = Column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    """Global Audit Log for all critical actions"""
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("idx_audit_logs_created", "created_at"),
        Index("idx_audit_logs_action",  "action"),
        Index("idx_audit_logs_user",    "user_id"),
    )

    id          = Column(Integer, primary_key=True, autoincrement=True)
    action      = Column(String(50), nullable=False)  # ORDER_CREATE | CONFIG_UPDATE | ...
    user_id     = Column(String(50), nullable=True)   # "system" or user id
    resource    = Column(String(100), nullable=True)  # "BTCUSDT" or "settings"
    details     = Column(JSONB, nullable=False, default={})
    ip_address  = Column(String(50), nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())


class ReplaySession(Base):
    """Historical Replay session configuration and status"""
    __tablename__ = "replay_sessions"
    __table_args__ = (
        Index("idx_replay_session_id", "replay_session_id", unique=True),
        Index("idx_replay_strategy",   "strategy_id"),
    )

    id                = Column(Integer, primary_key=True, autoincrement=True)
    replay_session_id = Column(String(50), nullable=False)
    strategy_id       = Column(Integer, nullable=False)
    strategy_type     = Column(String(20), nullable=True) # ma, rsi, etc.
    params            = Column(JSONB, nullable=True, default={}) # Strategy parameters
    symbol            = Column(String(20), nullable=False)
    start_time        = Column(DateTime(timezone=True), nullable=False)
    end_time          = Column(DateTime(timezone=True), nullable=False)
    speed             = Column(Integer, nullable=False, default=1) # 1, 10, 60, 100
    initial_capital   = Column(Float, nullable=False, default=100000.0)
    status            = Column(String(20), nullable=False, default="pending") # pending, running, completed, failed, paused
    current_timestamp = Column(DateTime(timezone=True), nullable=True)
    created_at        = Column(DateTime(timezone=True), server_default=func.now())
