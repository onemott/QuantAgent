"""
Add session-isolated replay accounts and initial_capital field.

Adds the paper_account_replay table for per-session balance isolation
during historical replay, and adds initial_capital to equity_snapshots
for accurate PnL calculation.

Revision ID: 002_add_replay_account_isolation
Revises: 001_initial_schema
Create Date: 2026-03-25

---

This migration is the companion to the真实性修复方案 v2.0.
Key changes:
- paper_account_replay: each replay session gets its own independent USDT balance,
  completely separate from the global PaperAccount(id=1) used by live paper trading.
- equity_snapshots.initial_capital: records the initial capital at session start
  for accurate return percentage calculation.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers
revision: str = "002_add_replay_account_isolation"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── paper_account_replay ────────────────────────────────────────────────────
    op.create_table(
        "paper_account_replay",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(64), unique=True, nullable=False),
        sa.Column("total_usdt", sa.Numeric(20, 8), nullable=False, server_default=sa.text("0")),
        sa.Column("initial_capital", sa.Numeric(20, 8), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            onupdate=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_paper_account_replay_session_id",
        "paper_account_replay",
        ["session_id"],
        unique=False,  # unique=True handled by table constraint
        postgresql_where=sa.text("session_id IS NOT NULL"),
    )

    # ── equity_snapshots.initial_capital ────────────────────────────────────────
    op.add_column(
        "equity_snapshots",
        sa.Column("initial_capital", sa.Numeric(20, 8), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("equity_snapshots", "initial_capital")
    op.drop_table("paper_account_replay")
