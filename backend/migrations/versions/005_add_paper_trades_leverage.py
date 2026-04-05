"""
Add leverage column to paper_trades table.

This is required so that LIMIT orders (especially in historical replay matching)
can carry the correct leverage into fill/position updates, instead of being
implicitly treated as 1x.

Revision ID: 005_add_paper_trades_leverage
Revises: 004_add_equity_snapshot_interval
Create Date: 2026-04-05
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision: str = "005_add_paper_trades_leverage"
down_revision: Union[str, None] = "004_add_equity_snapshot_interval"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) Add column with server_default to backfill existing rows safely.
    op.add_column(
        "paper_trades",
        sa.Column(
            "leverage",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )

    # 2) Comment for clarity (PostgreSQL).
    op.execute(
        """
        COMMENT ON COLUMN paper_trades.leverage
        IS '杠杆倍数（下单时记录），用于回放/限价单匹配时正确传递到持仓与清算价计算';
        """
    )

    # 3) Optional: keep server default for new rows at DB-level (safe fallback).
    # If you prefer app-level only defaults, you can drop server_default here.


def downgrade() -> None:
    op.drop_column("paper_trades", "leverage")

