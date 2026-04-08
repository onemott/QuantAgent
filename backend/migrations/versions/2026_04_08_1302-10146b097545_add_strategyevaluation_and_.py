"""Add StrategyEvaluation and SelectionHistory

Revision ID: 10146b097545
Revises: 005_add_paper_trades_leverage
Create Date: 2026-04-08 13:02:32.118082

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '10146b097545'
down_revision: Union[str, None] = '005_add_paper_trades_leverage'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('strategy_evaluations',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('strategy_id', sa.String(length=50), nullable=False),
        sa.Column('evaluation_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('window_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('window_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('total_return', sa.Float(), nullable=True),
        sa.Column('annual_return', sa.Float(), nullable=True),
        sa.Column('volatility', sa.Float(), nullable=True),
        sa.Column('max_drawdown', sa.Float(), nullable=True),
        sa.Column('sharpe_ratio', sa.Float(), nullable=True),
        sa.Column('sortino_ratio', sa.Float(), nullable=True),
        sa.Column('calmar_ratio', sa.Float(), nullable=True),
        sa.Column('win_rate', sa.Float(), nullable=True),
        sa.Column('num_trades', sa.Integer(), nullable=True),
        sa.Column('return_score', sa.Float(), nullable=True),
        sa.Column('risk_score', sa.Float(), nullable=True),
        sa.Column('risk_adjusted_score', sa.Float(), nullable=True),
        sa.Column('stability_score', sa.Float(), nullable=True),
        sa.Column('efficiency_score', sa.Float(), nullable=True),
        sa.Column('total_score', sa.Float(), nullable=True),
        sa.Column('rank', sa.Integer(), nullable=True),
        sa.Column('total_strategies', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_strategy_eval_strategy', 'strategy_evaluations', ['strategy_id'], unique=False)
    op.create_index('idx_strategy_eval_date', 'strategy_evaluations', ['evaluation_date'], unique=False)
    op.create_index('idx_strategy_eval_created', 'strategy_evaluations', ['created_at'], unique=False)

    from sqlalchemy.dialects import postgresql
    op.create_table('selection_history',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('evaluation_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('total_strategies', sa.Integer(), nullable=False, default=0),
        sa.Column('surviving_count', sa.Integer(), nullable=False, default=0),
        sa.Column('eliminated_count', sa.Integer(), nullable=False, default=0),
        sa.Column('eliminated_strategy_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=False, default=[]),
        sa.Column('elimination_reasons', postgresql.JSONB(astext_type=sa.Text()), nullable=False, default={}),
        sa.Column('strategy_weights', postgresql.JSONB(astext_type=sa.Text()), nullable=False, default={}),
        sa.Column('expected_return', sa.Float(), nullable=True),
        sa.Column('expected_volatility', sa.Float(), nullable=True),
        sa.Column('expected_sharpe', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_selection_history_date', 'selection_history', ['evaluation_date'], unique=False)
    op.create_index('idx_selection_history_created', 'selection_history', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_selection_history_created', table_name='selection_history')
    op.drop_index('idx_selection_history_date', table_name='selection_history')
    op.drop_table('selection_history')

    op.drop_index('idx_strategy_eval_created', table_name='strategy_evaluations')
    op.drop_index('idx_strategy_eval_date', table_name='strategy_evaluations')
    op.drop_index('idx_strategy_eval_strategy', table_name='strategy_evaluations')
    op.drop_table('strategy_evaluations')
