"""
SQLAlchemy ORM Models for QuantAgent OS
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional
from sqlalchemy import (
    Column,
    Integer,
    String,
    Numeric,
    DateTime,
    Text,
    CheckConstraint,
    Index,
    Boolean,
    Float,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector

Base = declarative_base()


class PaperAccount(Base):
    """Virtual trading account - always id=1"""

    __tablename__ = "paper_account"

    id = Column(Integer, primary_key=True, default=1)
    total_usdt = Column(Numeric(20, 8), nullable=False, default=100000.0)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PaperAccountReplay(Base):
    """Per-session virtual trading account for historical replay isolation.

    Each replay session has its own independent balance, completely separate
    from the global PaperAccount(id=1) used by live paper trading.
    This prevents session interference and ensures PnL calculations are accurate.
    """

    __tablename__ = "paper_account_replay"
    __table_args__ = (Index("idx_paper_account_replay_session_id", "session_id", unique=True),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), unique=True, nullable=False, index=True)
    total_usdt = Column(Numeric(20, 8), nullable=False, default=Decimal("0"))
    initial_capital = Column(Numeric(20, 8), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class PaperPosition(Base):
    """Current open positions (one row per symbol/session)"""

    __tablename__ = "paper_positions"
    __table_args__ = (Index("idx_paper_positions_session", "session_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False)
    session_id = Column(String(50), nullable=True)  # Added for isolation
    strategy_id = Column(String(30), nullable=True)  # Added for attribution
    quantity = Column(Numeric(20, 8), nullable=False, default=0)
    avg_price = Column(Numeric(20, 8), nullable=False, default=0)
    leverage = Column(Integer, nullable=False, default=1)
    liquidation_price = Column(Numeric(20, 8), nullable=True)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PaperTrade(Base):
    """Order / trade history"""

    __tablename__ = "paper_trades"
    __table_args__ = (
        CheckConstraint("side IN ('BUY', 'SELL')", name="ck_paper_trades_side"),
        Index("idx_paper_trades_symbol", "symbol"),
        Index("idx_paper_trades_created", "created_at"),
        Index("idx_paper_trades_client_order_id", "client_order_id", unique=True),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_id = Column(String(30), nullable=True)  # Added for attribution
    client_order_id = Column(
        String(50), nullable=True
    )  # Client-provided order ID for idempotency
    symbol = Column(String(20), nullable=False)
    side = Column(String(4), nullable=False)
    order_type = Column(String(10), nullable=False, default="MARKET")
    quantity = Column(Numeric(20, 8), nullable=False)
    price = Column(Numeric(20, 8), nullable=False)
    leverage = Column(Integer, nullable=False, default=1)
    benchmark_price = Column(Numeric(20, 8), nullable=True)
    fee = Column(Numeric(20, 8), nullable=False, default=0)
    funding_fee = Column(Numeric(20, 8), nullable=False, default=0)
    pnl = Column(Numeric(20, 8), nullable=True)
    status = Column(String(10), nullable=False, default="FILLED")
    mode = Column(
        String(20), nullable=False, default="paper"
    )  # paper | backtest | historical_replay
    session_id = Column(String(50), nullable=True)  # For historical_replay session_id
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    data_source = Column(String(20), nullable=False, default='PAPER')


class BacktestResult(Base):
    """Stored backtest run results"""

    __tablename__ = "backtest_results"
    __table_args__ = (
        Index("idx_backtest_created", "created_at"),
        Index("idx_backtest_strategy", "strategy_type", "symbol"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_type = Column(
        String(20), nullable=False
    )  # ma | rsi | boll | macd | ema_triple | atr_trend
    symbol = Column(String(20), nullable=False)
    interval = Column(String(5), nullable=False)
    params = Column(JSONB, nullable=False, default={})
    metrics = Column(JSONB, nullable=False, default={})
    equity_curve = Column(JSONB, nullable=False, default=[])
    trades_summary = Column(JSONB, nullable=False, default=[])
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    data_source = Column(String(20), nullable=False, default='BACKTEST')
    params_hash = Column(String(64), nullable=True)


class RiskEvent(Base):
    """Risk control event log — records every triggered or passed rule check"""

    __tablename__ = "risk_events"
    __table_args__ = (
        Index("idx_risk_events_symbol", "symbol"),
        Index("idx_risk_events_created", "created_at"),
        Index("idx_risk_events_rule", "rule"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False)
    rule = Column(
        String(50), nullable=False
    )  # MAX_SINGLE_POSITION | DRAWDOWN_HALT | DAILY_LOSS_HALT
    triggered = Column(Boolean, nullable=False, default=True)
    detail = Column(JSONB, nullable=False, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AgentMemory(Base):
    """Agent short-term memory — stores recent analysis summaries per agent+symbol"""

    __tablename__ = "agent_memories"
    __table_args__ = (
        Index("idx_agent_memories_agent_symbol", "agent_type", "symbol"),
        Index("idx_agent_memories_created", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_type = Column(String(30), nullable=False)  # trend | mean_reversion | risk
    symbol = Column(String(20), nullable=False)
    summary = Column(Text, nullable=False)

    # Enhanced Fields for RAG & RL
    reasoning_summary = Column(Text, nullable=True)
    signal = Column(
        String(20), nullable=True
    )  # BUY | SELL | WAIT | LONG_REVERSAL | ...
    action = Column(String(20), nullable=True)  # Actual action taken: BUY / SELL / HOLD
    confidence = Column(Float, nullable=True)  # 0.0 ~ 1.0
    entry_price = Column(Float, nullable=True)  # Price at the time of analysis

    # Vector Embedding (1536 dim for OpenAI text-embedding-3-small)
    market_state_embedding = Column(Vector(1536), nullable=True)

    outcome_pnl = Column(Float, nullable=True)  # PnL realized after N periods

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class OptimizationResult(Base):
    """Strategy parameter grid-search optimization results"""

    __tablename__ = "optimization_results"
    __table_args__ = (
        Index("idx_optim_strategy_symbol", "strategy_type", "symbol"),
        Index("idx_optim_created", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_type = Column(String(20), nullable=False)
    symbol = Column(String(20), nullable=False)
    interval = Column(String(5), nullable=False)
    params_grid = Column(
        JSONB, nullable=False, default={}
    )  # full grid results [{params, sharpe, ...}]
    best_params = Column(JSONB, nullable=False, default={})  # params with best sharpe
    best_sharpe = Column(Float, nullable=True)
    best_return = Column(Float, nullable=True)
    total_combos = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class TradePair(Base):
    """Trade pair - links entry and exit trades for P&L tracking"""

    __tablename__ = "trade_pairs"
    __table_args__ = (
        Index("idx_trade_pairs_pair", "pair_id"),
        Index("idx_trade_pairs_symbol", "symbol"),
        Index("idx_trade_pairs_status", "status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    pair_id = Column(String(36), nullable=False)  # UUID
    symbol = Column(String(20), nullable=False)
    strategy_id = Column(String(30), nullable=True)  # Added for attribution

    # Linked trade IDs
    entry_trade_id = Column(Integer, nullable=False)
    exit_trade_id = Column(Integer, nullable=True)

    # Pair info
    entry_time = Column(DateTime(timezone=True), nullable=False)
    exit_time = Column(DateTime(timezone=True), nullable=True)

    entry_price = Column(Numeric(20, 8), nullable=False)
    exit_price = Column(Numeric(20, 8), nullable=True)

    quantity = Column(Numeric(20, 8), nullable=False)
    side = Column(String(5), nullable=False)  # LONG or SHORT

    # Holding costs (fees + funding)
    holding_costs = Column(Numeric(20, 8), nullable=False, default=0)

    # Pair status
    status = Column(String(10), nullable=False, default="OPEN")  # OPEN | CLOSED
    pnl = Column(Numeric(20, 8), nullable=True)
    pnl_pct = Column(Numeric(10, 4), nullable=True)

    # Holding duration (hours)
    holding_hours = Column(Numeric(10, 2), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class EquitySnapshot(Base):
    """Periodic equity curve snapshot (hourly)"""

    __tablename__ = "equity_snapshots"
    __table_args__ = (
        Index("idx_equity_timestamp", "timestamp"),
        Index("idx_equity_session", "session_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    session_id = Column(String(50), nullable=True)  # For historical replay isolation
    total_equity = Column(Numeric(20, 8), nullable=False)
    cash_balance = Column(Numeric(20, 8), nullable=False)
    position_value = Column(Numeric(20, 8), nullable=False, default=0)
    daily_pnl = Column(Numeric(20, 8), nullable=True, default=0)
    daily_return = Column(Numeric(10, 6), nullable=True, default=0)
    drawdown = Column(Numeric(10, 6), nullable=True, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    data_source = Column(String(20), nullable=False, default='PAPER')
    initial_capital = Column(Numeric(20, 8), nullable=True)  # For replay PnL calculation


class PerformanceMetric(Base):
    """Aggregated performance metrics over a time period"""

    __tablename__ = "performance_metrics"
    __table_args__ = (Index("idx_perf_period", "period"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    period = Column(String(20), nullable=False)  # daily | weekly | monthly | all_time
    start_date = Column(DateTime(timezone=True), nullable=False)
    end_date = Column(DateTime(timezone=True), nullable=False)

    # Basic metrics
    initial_equity = Column(Numeric(20, 8), nullable=False)
    final_equity = Column(Numeric(20, 8), nullable=False)
    total_return = Column(Numeric(10, 4), nullable=False, default=0)
    total_trades = Column(Integer, nullable=False, default=0)
    winning_trades = Column(Integer, nullable=False, default=0)
    losing_trades = Column(Integer, nullable=False, default=0)

    # Risk metrics
    max_drawdown = Column(Numeric(10, 4), nullable=False, default=0)
    max_drawdown_pct = Column(Numeric(10, 4), nullable=False, default=0)
    volatility = Column(Numeric(10, 4), nullable=False, default=0)

    # Return metrics
    annualized_return = Column(Numeric(10, 4), nullable=False, default=0)
    sharpe_ratio = Column(Numeric(10, 4), nullable=True)
    sortino_ratio = Column(Numeric(10, 4), nullable=True)
    calmar_ratio = Column(Numeric(10, 4), nullable=True)

    # Trade metrics
    win_rate = Column(Numeric(10, 4), nullable=False, default=0)
    profit_factor = Column(Numeric(10, 4), nullable=True)
    avg_holding_hours = Column(Numeric(10, 2), nullable=True)
    max_consecutive_wins = Column(Integer, default=0)
    max_consecutive_losses = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    """Global Audit Log for all critical actions"""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("idx_audit_logs_created", "created_at"),
        Index("idx_audit_logs_action", "action"),
        Index("idx_audit_logs_user", "user_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    action = Column(String(50), nullable=False)  # ORDER_CREATE | CONFIG_UPDATE | ...
    user_id = Column(String(50), nullable=True)  # "system" or user id
    resource = Column(String(100), nullable=True)  # "BTCUSDT" or "settings"
    details = Column(JSONB, nullable=False, default={})
    ip_address = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ReplaySession(Base):
    """Historical Replay session configuration and status"""

    __tablename__ = "replay_sessions"
    __table_args__ = (
        Index("idx_replay_session_id", "replay_session_id", unique=True),
        Index("idx_replay_strategy", "strategy_id"),
        Index("idx_replay_saved", "is_saved"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    replay_session_id = Column(String(50), nullable=False)
    strategy_id = Column(Integer, nullable=False)
    strategy_type = Column(String(20), nullable=True)  # ma, rsi, etc.
    params = Column(JSONB, nullable=True, default={})  # Strategy parameters
    symbol = Column(String(20), nullable=False)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    speed = Column(Integer, nullable=False, default=1)  # 1, 10, 60, 100
    initial_capital = Column(Float, nullable=False, default=100000.0)
    status = Column(
        String(20), nullable=False, default="pending"
    )  # pending, running, completed, failed, paused
    current_timestamp = Column(DateTime(timezone=True), nullable=True)
    is_saved = Column(Boolean, nullable=False, default=False)  # 是否保存记录
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())
    data_source = Column(String(20), nullable=False, default='REPLAY')
    backtest_id = Column(Integer, nullable=True)  # FK set via separate migration
    params_hash = Column(String(64), nullable=True)
    equity_snapshot_interval = Column(Integer, nullable=False, default=3600)  # 权益快照间隔（秒），默认3600（1小时）
    metrics = Column(JSONB, nullable=False, default=dict)


class StrategyDefaultParam(Base):
    """Stored default parameters for strategy templates.
    Used to persist optimized/manual parameters so they sync across pages."""

    __tablename__ = "strategy_default_params"
    __table_args__ = (
        Index("idx_strategy_params_type", "strategy_type"),
        UniqueConstraint("strategy_type", "param_key", name="uq_strategy_param"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_type = Column(String(50), nullable=False)
    param_key = Column(String(100), nullable=False)
    param_value = Column(Float, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by = Column(
        String(100), nullable=False, default="system"
    )  # optimization, manual_backtest, manual_replay


class StrategyParamHistory(Base):
    """History of strategy parameter changes for audit trail."""

    __tablename__ = "strategy_param_history"
    __table_args__ = (Index("idx_param_history_type", "strategy_type"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_type = Column(String(50), nullable=False)
    param_key = Column(String(100), nullable=False)
    old_value = Column(Float, nullable=True)
    new_value = Column(Float, nullable=False)
    changed_at = Column(DateTime(timezone=True), server_default=func.now())
    changed_by = Column(String(100), nullable=False, default="system")
    reason = Column(String(500), nullable=True)  # optimization, manual_adjustment, etc.


class CompositionResult(Base):
    """策略组合优化结果存储"""
    
    __tablename__ = "composition_results"
    __table_args__ = (
        Index("idx_composition_type_symbol", "composition_type", "symbol"),
        Index("idx_composition_created", "created_at"),
    )
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # 组合配置
    composition_type = Column(String(20), nullable=False)  # 'weighted', 'voting'
    atomic_strategies = Column(JSONB, nullable=False, default=[])  # ['ma', 'rsi', 'boll']
    
    # 标的和周期
    symbol = Column(String(20), nullable=False)
    interval = Column(String(5), nullable=False)
    
    # 最佳参数
    best_params = Column(JSONB, nullable=False, default={})
    
    # 性能指标
    best_performance = Column(JSONB, nullable=False, default={})
    best_sharpe = Column(Float, nullable=True)
    best_return = Column(Float, nullable=True)
    
    # 优化统计
    total_combinations_tested = Column(Integer, nullable=True)
    valid_results = Column(Integer, nullable=True)
    
    # 详细结果（前N个）
    all_results = Column(JSONB, nullable=False, default=[])
    
    # 时间戳
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class SkillDefinitionDB(Base):
    """Skill定义数据库模型"""
    
    __tablename__ = "skill_definitions"
    __table_args__ = (
        Index("idx_skill_type_status", "skill_type", "status"),
        Index("idx_skill_created", "created_at"),
        Index("idx_skill_author", "author"),
    )
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Skill标识
    skill_id = Column(String(100), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    
    # Skill类型和分类
    skill_type = Column(String(50), nullable=False)  # strategy_generator, optimization_evaluator, etc.
    category = Column(String(50), nullable=True)
    
    # 版本信息
    version = Column(String(20), nullable=False, default="1.0.0")
    status = Column(String(20), nullable=False, default="active")  # active, inactive, deprecated
    
    # 配置和参数
    input_schema = Column(JSONB, nullable=False, default={})
    output_schema = Column(JSONB, nullable=False, default={})
    parameters = Column(JSONB, nullable=False, default={})
    dependencies = Column(JSONB, nullable=False, default=[])  # 依赖库列表
    
    # 执行配置
    timeout_seconds = Column(Integer, nullable=True)  # 超时时间
    max_retries = Column(Integer, nullable=False, default=3)
    concurrency_limit = Column(Integer, nullable=False, default=1)
    
    # 实现信息
    implementation_path = Column(String(500), nullable=True)  # 模块路径
    code_content = Column(Text, nullable=True)  # 代码内容（可选）
    
    # 元数据
    author = Column(String(100), nullable=True)
    tags = Column(JSONB, nullable=False, default=[])
    
    # 性能统计
    execution_count = Column(Integer, nullable=False, default=0)
    success_count = Column(Integer, nullable=False, default=0)
    avg_execution_time = Column(Float, nullable=True)
    
    # 时间戳
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_executed_at = Column(DateTime(timezone=True), nullable=True)


class WFOSession(Base):
    """Walk-Forward Optimization Session"""

    __tablename__ = "wfo_sessions"
    __table_args__ = (
        Index("idx_wfo_sessions_strategy_symbol", "strategy_type", "symbol"),
        Index("idx_wfo_sessions_created", "created_at"),
        Index("idx_wfo_sessions_status", "status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_type = Column(String(50), nullable=False)
    symbol = Column(String(20), nullable=False)
    interval = Column(String(5), nullable=False)
    
    # WFA Configuration
    is_days = Column(Integer, nullable=False)
    oos_days = Column(Integer, nullable=False)
    step_days = Column(Integer, nullable=False)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    initial_capital = Column(Float, nullable=False, default=100000.0)
    
    # Execution Status
    status = Column(String(20), nullable=False, default="pending")  # pending, running, completed, failed
    error_message = Column(Text, nullable=True)
    
    # Overall Results
    metrics = Column(JSONB, nullable=False, default={})  # Overall WFE, PS, etc.
    equity_curve = Column(JSONB, nullable=False, default=[])  # Stitched OOS equity curve
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class WFOWindowResult(Base):
    """Walk-Forward Optimization Window Result"""

    __tablename__ = "wfo_window_results"
    __table_args__ = (
        Index("idx_wfo_windows_session", "wfo_session_id"),
        Index("idx_wfo_windows_index", "wfo_session_id", "window_index"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    wfo_session_id = Column(Integer, nullable=False)  # Links to WFOSession.id
    window_index = Column(Integer, nullable=False)
    
    # Window Boundaries
    is_start_time = Column(DateTime(timezone=True), nullable=False)
    is_end_time = Column(DateTime(timezone=True), nullable=False)
    oos_start_time = Column(DateTime(timezone=True), nullable=False)
    oos_end_time = Column(DateTime(timezone=True), nullable=False)
    
    # Window Results
    best_params = Column(JSONB, nullable=False, default={})
    is_metrics = Column(JSONB, nullable=False, default={})
    oos_metrics = Column(JSONB, nullable=False, default={})
    
    # Stability Metrics
    wfe = Column(Float, nullable=True)  # Walk-Forward Efficiency (OOS / IS annualized return ratio)
    param_stability = Column(Float, nullable=True)  # Parameter drift metric
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class StrategyEvaluation(Base):
    """策略评估记录"""
    
    __tablename__ = "strategy_evaluations"
    __table_args__ = (
        Index("idx_strategy_eval_strategy", "strategy_id"),
        Index("idx_strategy_eval_date", "evaluation_date"),
        Index("idx_strategy_eval_created", "created_at"),
    )
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_id = Column(String(50), nullable=False)
    evaluation_date = Column(DateTime(timezone=True), nullable=False)
    
    # 评估窗口
    window_start = Column(DateTime(timezone=True), nullable=False)
    window_end = Column(DateTime(timezone=True), nullable=False)
    
    # 基础绩效
    total_return = Column(Float, nullable=True)
    annual_return = Column(Float, nullable=True)
    volatility = Column(Float, nullable=True)
    max_drawdown = Column(Float, nullable=True)
    sharpe_ratio = Column(Float, nullable=True)
    sortino_ratio = Column(Float, nullable=True)
    calmar_ratio = Column(Float, nullable=True)
    win_rate = Column(Float, nullable=True)
    num_trades = Column(Integer, nullable=True)
    
    # 综合得分
    return_score = Column(Float, nullable=True)
    risk_score = Column(Float, nullable=True)
    risk_adjusted_score = Column(Float, nullable=True)
    stability_score = Column(Float, nullable=True)
    efficiency_score = Column(Float, nullable=True)
    total_score = Column(Float, nullable=True)
    
    # 排名
    rank = Column(Integer, nullable=True)
    total_strategies = Column(Integer, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class SelectionHistory(Base):
    """选择历史记录"""
    
    __tablename__ = "selection_history"
    __table_args__ = (
        Index("idx_selection_history_date", "evaluation_date"),
        Index("idx_selection_history_created", "created_at"),
    )
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    evaluation_date = Column(DateTime(timezone=True), nullable=False)
    
    # 策略池状态
    total_strategies = Column(Integer, nullable=False, default=0)
    surviving_count = Column(Integer, nullable=False, default=0)
    eliminated_count = Column(Integer, nullable=False, default=0)
    
    # 淘汰详情
    eliminated_strategy_ids = Column(JSONB, nullable=False, default=[])
    elimination_reasons = Column(JSONB, nullable=False, default={})
    
    # 权重分配
    strategy_weights = Column(JSONB, nullable=False, default={})
    
    # 组合绩效预测
    expected_return = Column(Float, nullable=True)
    expected_volatility = Column(Float, nullable=True)
    expected_sharpe = Column(Float, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class SkillExecutionDB(Base):
    """Skill执行记录数据库模型"""
    
    __tablename__ = "skill_executions"
    __table_args__ = (
        Index("idx_execution_skill", "skill_id"),
        Index("idx_execution_status", "status"),
        Index("idx_execution_created", "created_at"),
        Index("idx_execution_hash", "inputs_hash"),
    )
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # 执行标识
    execution_id = Column(String(100), unique=True, nullable=False, index=True)
    skill_id = Column(String(100), nullable=False, index=True)
    skill_version = Column(String(20), nullable=False)
    
    # 执行状态
    status = Column(String(20), nullable=False)  # pending, running, completed, failed, cancelled
    success = Column(Boolean, nullable=False)
    
    # 输入输出
    inputs = Column(JSONB, nullable=False, default={})
    inputs_hash = Column(String(64), nullable=True, index=True)  # 输入哈希，用于去重
    parameters = Column(JSONB, nullable=False, default={})
    context = Column(JSONB, nullable=True)
    
    # 结果
    result_data = Column(JSONB, nullable=True)
    error_message = Column(Text, nullable=True)
    error_details = Column(JSONB, nullable=True)
    
    # 性能指标
    execution_time = Column(Float, nullable=True)  # 执行时间（秒）
    queue_time = Column(Float, nullable=True)  # 排队时间（秒）
    
    # 时间戳
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    # 关联
    parent_execution_id = Column(String(100), nullable=True, index=True)  # 父执行ID，用于工作流
    workflow_id = Column(String(100), nullable=True, index=True)  # 所属工作流ID
    
    # 元数据
    executed_by = Column(String(100), nullable=True, default="system")
    execution_tags = Column(JSONB, nullable=False, default=[])


class SkillMetricDB(Base):
    """Skill性能指标数据库模型"""
    
    __tablename__ = "skill_metrics"
    __table_args__ = (
        Index("idx_metric_skill_period", "skill_id", "period_start"),
        Index("idx_metric_created", "created_at"),
    )
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # 关联
    skill_id = Column(String(100), nullable=False, index=True)
    
    # 统计周期
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)
    period_type = Column(String(20), nullable=False)  # hourly, daily, weekly, monthly
    
    # 执行统计
    total_executions = Column(Integer, nullable=False, default=0)
    successful_executions = Column(Integer, nullable=False, default=0)
    failed_executions = Column(Integer, nullable=False, default=0)
    cancelled_executions = Column(Integer, nullable=False, default=0)
    
    # 性能指标
    avg_execution_time = Column(Float, nullable=True)
    min_execution_time = Column(Float, nullable=True)
    max_execution_time = Column(Float, nullable=True)
    avg_queue_time = Column(Float, nullable=True)
    
    # 成功率
    success_rate = Column(Float, nullable=True)
    
    # 错误统计
    error_types = Column(JSONB, nullable=False, default={})  # 错误类型分布
    
    # 时间戳
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class SkillWorkflowDB(Base):
    """Skill工作流数据库模型"""
    
    __tablename__ = "skill_workflows"
    __table_args__ = (
        Index("idx_workflow_status", "status"),
        Index("idx_workflow_created", "created_at"),
    )
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # 工作流标识
    workflow_id = Column(String(100), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    
    # 工作流定义
    workflow_definition = Column(JSONB, nullable=False, default={})  # 工作流步骤定义
    parameters = Column(JSONB, nullable=False, default={})
    
    # 状态
    status = Column(String(20), nullable=False, default="draft")  # draft, active, inactive
    
    # 执行统计
    execution_count = Column(Integer, nullable=False, default=0)
    success_count = Column(Integer, nullable=False, default=0)
    
    # 元数据
    author = Column(String(100), nullable=True)
    tags = Column(JSONB, nullable=False, default=[])
    version = Column(String(20), nullable=False, default="1.0.0")
    
    # 时间戳
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_executed_at = Column(DateTime(timezone=True), nullable=True)
