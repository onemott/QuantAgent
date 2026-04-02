"""
Add equity_snapshot_interval column to replay_sessions table.

This migration adds a configurable snapshot granularity for equity tracking
during replay sessions. The default is 3600 seconds (1 hour).

Revision ID: 004_add_equity_snapshot_interval
Revises: 003_add_skill_tables
Create Date: 2026-04-02

---

The equity_snapshot_interval column controls how frequently equity snapshots
are recorded during a replay session. Valid range: 60-14400 seconds
(1 minute to 4 hours).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision: str = "004_add_equity_snapshot_interval"
down_revision: Union[str, None] = "003_add_skill_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add equity_snapshot_interval column with default 3600 (1 hour)
    op.add_column(
        "replay_sessions",
        sa.Column(
            "equity_snapshot_interval",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("3600"),
        ),
    )
    
    # Add comment for documentation
    op.execute(
        """
        COMMENT ON COLUMN replay_sessions.equity_snapshot_interval 
        IS '权益快照间隔（秒），范围：60-14400，默认3600（1小时）';
        """
    )


def downgrade() -> None:
    # Remove the equity_snapshot_interval column
    op.drop_column("replay_sessions", "equity_snapshot_interval")
