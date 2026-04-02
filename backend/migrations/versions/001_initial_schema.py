"""
Initial schema — QuantAgent OS baseline migration.

Creates all 15 tables with their columns, indexes, constraints, and extensions.
This migration represents the complete schema state after the original init-scripts.

Revision ID: 001_initial_schema
Revises: None (initial)
Create Date: 2026-03-23

---
This migration replaces the standalone SQL init-scripts. Future schema changes
should be made through Alembic migrations (alembic revision --autogenerate).

Transition plan for existing databases:
  1. Ensure all init-scripts have already run (database is at current state).
  2. Stamp this baseline migration as applied:
     python scripts/run_migrations.py stamp 001_initial_schema
  3. Future changes via: alembic revision --autogenerate -m "description"
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Extensions ────────────────────────────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── paper_account ────────────────────────────────────────────────────────
    op.create_table(
        "paper_account",
        sa.Column("id", sa.Integer(), primary_key=True, server_default=sa.text("1")),
        sa.Column("total_usdt", sa.Numeric(20, 8), nullable=False, server_default=sa.text("100000.00000000")),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            onupdate=sa.text("now()"),
        ),
    )

    # ── paper_positions ──────────────────────────────────────────────────────
    op.create_table(
        "paper_positions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("session_id", sa.String(50), nullable=True),
        sa.Column("strategy_id", sa.String(30), nullable=True),
        sa.Column("quantity", sa.Numeric(20, 8), nullable=False, server_default=sa.text("0")),
        sa.Column("avg_price", sa.Numeric(20, 8), nullable=False, server_default=sa.text("0")),
        sa.Column("leverage", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("liquidation_price", sa.Numeric(20, 8), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            onupdate=sa.text("now()"),
        ),
    )
    op.create_index("idx_paper_positions_session", "paper_positions", ["session_id"])

    # ── paper_trades ─────────────────────────────────────────────────────────
    op.create_table(
        "paper_trades",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("strategy_id", sa.String(30), nullable=True),
        sa.Column("client_order_id", sa.String(50), nullable=True),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("order_type", sa.String(10), nullable=False, server_default=sa.text("'MARKET'::character varying")),
        sa.Column("quantity", sa.Numeric(20, 8), nullable=False),
        sa.Column("price", sa.Numeric(20, 8), nullable=False),
        sa.Column("benchmark_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("fee", sa.Numeric(20, 8), nullable=False, server_default=sa.text("0")),
        sa.Column("funding_fee", sa.Numeric(20, 8), nullable=False, server_default=sa.text("0")),
        sa.Column("pnl", sa.Numeric(20, 8), nullable=True),
        sa.Column("status", sa.String(10), nullable=False, server_default=sa.text("'FILLED'::character varying")),
        sa.Column("mode", sa.String(20), nullable=False, server_default=sa.text("'paper'::character varying")),
        sa.Column("session_id", sa.String(50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column("data_source", sa.String(20), nullable=False, server_default=sa.text("'PAPER'::character varying")),
        sa.CheckConstraint("side IN ('BUY', 'SELL')", name="ck_paper_trades_side"),
    )
    op.create_index("idx_paper_trades_symbol", "paper_trades", ["symbol"])
    op.create_index("idx_paper_trades_created", "paper_trades", ["created_at"])
    op.create_index(
        "idx_paper_trades_client_order_id",
        "paper_trades",
        ["client_order_id"],
        unique=True,
        postgresql_where=sa.text("client_order_id IS NOT NULL"),
    )

    # ── backtest_results ─────────────────────────────────────────────────────
    op.create_table(
        "backtest_results",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("strategy_type", sa.String(20), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("interval", sa.String(5), nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("equity_curve", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("trades_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column("data_source", sa.String(20), nullable=False, server_default=sa.text("'BACKTEST'::character varying")),
        sa.Column("params_hash", sa.String(64), nullable=True),
    )
    op.create_index("idx_backtest_created", "backtest_results", ["created_at"])
    op.create_index("idx_backtest_strategy", "backtest_results", ["strategy_type", "symbol"])
    op.create_index("idx_backtest_data_source", "backtest_results", ["data_source"])
    op.create_index("idx_backtest_params_hash", "backtest_results", ["params_hash"])

    # ── risk_events ──────────────────────────────────────────────────────────
    op.create_table(
        "risk_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("rule", sa.String(50), nullable=False),
        sa.Column("triggered", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_risk_events_symbol", "risk_events", ["symbol"])
    op.create_index("idx_risk_events_created", "risk_events", ["created_at"])
    op.create_index("idx_risk_events_rule", "risk_events", ["rule"])

    # ── agent_memories ───────────────────────────────────────────────────────
    op.create_table(
        "agent_memories",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("agent_type", sa.String(30), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("reasoning_summary", sa.Text(), nullable=True),
        sa.Column("signal", sa.String(20), nullable=True),
        sa.Column("action", sa.String(20), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("entry_price", sa.Float(), nullable=True),
        # market_state_embedding (vector 1536) added separately via op.execute below
        sa.Column("outcome_pnl", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_agent_memories_agent_symbol", "agent_memories", ["agent_type", "symbol"])
    op.create_index("idx_agent_memories_created", "agent_memories", ["created_at"])
    # Add pgvector column after table creation (VECTOR is pgvector-specific)
    op.execute("""
        ALTER TABLE agent_memories
        ADD COLUMN IF NOT EXISTS market_state_embedding vector(1536)
    """)

    # ── optimization_results ──────────────────────────────────────────────────
    op.create_table(
        "optimization_results",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("strategy_type", sa.String(20), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("interval", sa.String(5), nullable=False),
        sa.Column("params_grid", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("best_params", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("best_sharpe", sa.Float(), nullable=True),
        sa.Column("best_return", sa.Float(), nullable=True),
        sa.Column("total_combos", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_optim_strategy_symbol", "optimization_results", ["strategy_type", "symbol"])
    op.create_index("idx_optim_created", "optimization_results", ["created_at"])

    # ── trade_pairs ──────────────────────────────────────────────────────────
    op.create_table(
        "trade_pairs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("pair_id", sa.String(36), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("strategy_id", sa.String(30), nullable=True),
        sa.Column("entry_trade_id", sa.Integer(), nullable=False),
        sa.Column("exit_trade_id", sa.Integer(), nullable=True),
        sa.Column("entry_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exit_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("entry_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("exit_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("quantity", sa.Numeric(20, 8), nullable=False),
        sa.Column("side", sa.String(5), nullable=False),
        sa.Column("holding_costs", sa.Numeric(20, 8), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(10), nullable=False, server_default=sa.text("'OPEN'::character varying")),
        sa.Column("pnl", sa.Numeric(20, 8), nullable=True),
        sa.Column("pnl_pct", sa.Numeric(10, 4), nullable=True),
        sa.Column("holding_hours", sa.Numeric(10, 2), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_trade_pairs_pair", "trade_pairs", ["pair_id"])
    op.create_index("idx_trade_pairs_symbol", "trade_pairs", ["symbol"])
    op.create_index("idx_trade_pairs_status", "trade_pairs", ["status"])

    # ── equity_snapshots ─────────────────────────────────────────────────────
    op.create_table(
        "equity_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("session_id", sa.String(50), nullable=True),
        sa.Column("total_equity", sa.Numeric(20, 8), nullable=False),
        sa.Column("cash_balance", sa.Numeric(20, 8), nullable=False),
        sa.Column("position_value", sa.Numeric(20, 8), nullable=False, server_default=sa.text("0")),
        sa.Column("daily_pnl", sa.Numeric(20, 8), nullable=True, server_default=sa.text("0")),
        sa.Column("daily_return", sa.Numeric(10, 6), nullable=True, server_default=sa.text("0")),
        sa.Column("drawdown", sa.Numeric(10, 6), nullable=True, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column("data_source", sa.String(20), nullable=False, server_default=sa.text("'PAPER'::character varying")),
    )
    op.create_index("idx_equity_timestamp", "equity_snapshots", ["timestamp"])
    op.create_index("idx_equity_session", "equity_snapshots", ["session_id"])

    # ── performance_metrics ───────────────────────────────────────────────────
    op.create_table(
        "performance_metrics",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("period", sa.String(20), nullable=False),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("initial_equity", sa.Numeric(20, 8), nullable=False),
        sa.Column("final_equity", sa.Numeric(20, 8), nullable=False),
        sa.Column("total_return", sa.Numeric(10, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("total_trades", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("winning_trades", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("losing_trades", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_drawdown", sa.Numeric(10, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("max_drawdown_pct", sa.Numeric(10, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("volatility", sa.Numeric(10, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("annualized_return", sa.Numeric(10, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("sharpe_ratio", sa.Numeric(10, 4), nullable=True),
        sa.Column("sortino_ratio", sa.Numeric(10, 4), nullable=True),
        sa.Column("calmar_ratio", sa.Numeric(10, 4), nullable=True),
        sa.Column("win_rate", sa.Numeric(10, 4), nullable=False, server_default=sa.text("0")),
        sa.Column("profit_factor", sa.Numeric(10, 4), nullable=True),
        sa.Column("avg_holding_hours", sa.Numeric(10, 2), nullable=True),
        sa.Column("max_consecutive_wins", sa.Integer(), server_default=sa.text("0")),
        sa.Column("max_consecutive_losses", sa.Integer(), server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_perf_period", "performance_metrics", ["period"])

    # ── audit_logs ────────────────────────────────────────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("user_id", sa.String(50), nullable=True),
        sa.Column("resource", sa.String(100), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("ip_address", sa.String(50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_audit_logs_created", "audit_logs", ["created_at"])
    op.create_index("idx_audit_logs_action", "audit_logs", ["action"])
    op.create_index("idx_audit_logs_user", "audit_logs", ["user_id"])

    # ── replay_sessions ────────────────────────────────────────────────────────
    op.create_table(
        "replay_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("replay_session_id", sa.String(50), nullable=False),
        sa.Column("strategy_id", sa.Integer(), nullable=False),
        sa.Column("strategy_type", sa.String(20), nullable=True),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default=sa.text("'{}'::jsonb")),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("speed", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("initial_capital", sa.Float(), nullable=False, server_default=sa.text("100000.0")),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'pending'::character varying")),
        sa.Column("current_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_saved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            onupdate=sa.text("now()"),
        ),
        sa.Column("data_source", sa.String(20), nullable=False, server_default=sa.text("'REPLAY'::character varying")),
        sa.Column("backtest_id", sa.Integer(), nullable=True),
        sa.Column("params_hash", sa.String(64), nullable=True),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index("idx_replay_session_id", "replay_sessions", ["replay_session_id"], unique=True)
    op.create_index("idx_replay_strategy", "replay_sessions", ["strategy_id"])
    op.create_index("idx_replay_saved", "replay_sessions", ["is_saved"], postgresql_where=sa.text("is_saved = true"))
    op.create_index("idx_replay_sessions_status", "replay_sessions", ["status"])
    op.create_index("idx_replay_sessions_created", "replay_sessions", ["created_at"])
    op.create_index("idx_replay_sessions_backtest", "replay_sessions", ["backtest_id"])
    op.create_index("idx_replay_sessions_params_hash", "replay_sessions", ["params_hash"])

    # ── strategy_default_params ──────────────────────────────────────────────
    op.create_table(
        "strategy_default_params",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("strategy_type", sa.String(50), nullable=False),
        sa.Column("param_key", sa.String(100), nullable=False),
        sa.Column("param_value", sa.Float(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            onupdate=sa.text("now()"),
        ),
        sa.Column(
            "updated_by",
            sa.String(100),
            nullable=False,
            server_default=sa.text("'system'::character varying"),
        ),
        sa.UniqueConstraint("strategy_type", "param_key", name="uq_strategy_param"),
    )
    op.create_index("idx_strategy_params_type", "strategy_default_params", ["strategy_type"])

    # ── strategy_param_history ────────────────────────────────────────────────
    op.create_table(
        "strategy_param_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("strategy_type", sa.String(50), nullable=False),
        sa.Column("param_key", sa.String(100), nullable=False),
        sa.Column("old_value", sa.Float(), nullable=True),
        sa.Column("new_value", sa.Float(), nullable=False),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "changed_by",
            sa.String(100),
            nullable=False,
            server_default=sa.text("'system'::character varying"),
        ),
        sa.Column("reason", sa.String(500), nullable=True),
    )
    op.create_index("idx_param_history_type", "strategy_param_history", ["strategy_type"])


def downgrade() -> None:
    """Drop all tables in reverse dependency order (child → parent)."""
    op.drop_table("strategy_param_history")
    op.drop_table("strategy_default_params")
    op.drop_table("replay_sessions")
    op.drop_table("audit_logs")
    op.drop_table("performance_metrics")
    op.drop_table("equity_snapshots")
    op.drop_table("trade_pairs")
    op.drop_table("optimization_results")
    op.drop_table("agent_memories")
    op.drop_table("risk_events")
    op.drop_table("backtest_results")
    op.drop_table("paper_trades")
    op.drop_table("paper_positions")
    op.drop_table("paper_account")
    # Note: We do NOT drop the 'vector' extension as other objects may depend on it.
