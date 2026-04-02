"""
Add Skill system tables for the Skill framework.

Creates 4 tables to support the Skill execution and management system:
- skill_definitions: Stores skill metadata, schemas, and configurations
- skill_executions: Records individual skill execution history
- skill_metrics: Aggregates performance metrics per skill over time periods
- skill_workflows: Defines multi-step skill workflows

Revision ID: 003_add_skill_tables
Revises: 002_add_replay_account_isolation
Create Date: 2026-04-02

---

This migration supports the Skill system framework which enables:
- Custom skill definition with input/output schemas
- Execution tracking with deduplication support
- Performance metrics aggregation
- Multi-step workflow orchestration
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers
revision: str = "003_add_skill_tables"
down_revision: Union[str, None] = "002_add_replay_account_isolation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── skill_definitions ─────────────────────────────────────────────────────
    op.create_table(
        "skill_definitions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        # Skill标识
        sa.Column("skill_id", sa.String(100), unique=True, nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        # Skill类型和分类
        sa.Column("skill_type", sa.String(50), nullable=False),
        sa.Column("category", sa.String(50), nullable=True),
        # 版本信息
        sa.Column("version", sa.String(20), nullable=False, server_default=sa.text("'1.0.0'::character varying")),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'active'::character varying")),
        # 配置和参数
        sa.Column("input_schema", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("output_schema", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("parameters", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("dependencies", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        # 执行配置
        sa.Column("timeout_seconds", sa.Integer(), nullable=True),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default=sa.text("3")),
        sa.Column("concurrency_limit", sa.Integer(), nullable=False, server_default=sa.text("1")),
        # 实现信息
        sa.Column("implementation_path", sa.String(500), nullable=True),
        sa.Column("code_content", sa.Text(), nullable=True),
        # 元数据
        sa.Column("author", sa.String(100), nullable=True),
        sa.Column("tags", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        # 性能统计
        sa.Column("execution_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("avg_execution_time", sa.Float(), nullable=True),
        # 时间戳
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.text("now()")),
        sa.Column("last_executed_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Indexes for skill_definitions
    op.create_index("idx_skill_definitions_skill_id", "skill_definitions", ["skill_id"], unique=True)
    op.create_index("idx_skill_type_status", "skill_definitions", ["skill_type", "status"])
    op.create_index("idx_skill_created", "skill_definitions", ["created_at"])
    op.create_index("idx_skill_author", "skill_definitions", ["author"])

    # ── skill_executions ──────────────────────────────────────────────────────
    op.create_table(
        "skill_executions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        # 执行标识
        sa.Column("execution_id", sa.String(100), unique=True, nullable=False),
        sa.Column("skill_id", sa.String(100), nullable=False),
        sa.Column("skill_version", sa.String(20), nullable=False),
        # 执行状态
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        # 输入输出
        sa.Column("inputs", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("inputs_hash", sa.String(64), nullable=True),
        sa.Column("parameters", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("context", postgresql.JSONB(), nullable=True),
        # 结果
        sa.Column("result_data", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_details", postgresql.JSONB(), nullable=True),
        # 性能指标
        sa.Column("execution_time", sa.Float(), nullable=True),
        sa.Column("queue_time", sa.Float(), nullable=True),
        # 时间戳
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        # 关联
        sa.Column("parent_execution_id", sa.String(100), nullable=True),
        sa.Column("workflow_id", sa.String(100), nullable=True),
        # 元数据
        sa.Column("executed_by", sa.String(100), nullable=True, server_default=sa.text("'system'::character varying")),
        sa.Column("execution_tags", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    # Indexes for skill_executions
    op.create_index("idx_skill_executions_execution_id", "skill_executions", ["execution_id"], unique=True)
    op.create_index("idx_execution_skill", "skill_executions", ["skill_id"])
    op.create_index("idx_execution_status", "skill_executions", ["status"])
    op.create_index("idx_execution_created", "skill_executions", ["created_at"])
    op.create_index("idx_execution_hash", "skill_executions", ["inputs_hash"])
    op.create_index("idx_skill_executions_parent", "skill_executions", ["parent_execution_id"])
    op.create_index("idx_skill_executions_workflow", "skill_executions", ["workflow_id"])

    # ── skill_metrics ─────────────────────────────────────────────────────────
    op.create_table(
        "skill_metrics",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        # 关联
        sa.Column("skill_id", sa.String(100), nullable=False),
        # 统计周期
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_type", sa.String(20), nullable=False),
        # 执行统计
        sa.Column("total_executions", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("successful_executions", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("failed_executions", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("cancelled_executions", sa.Integer(), nullable=False, server_default=sa.text("0")),
        # 性能指标
        sa.Column("avg_execution_time", sa.Float(), nullable=True),
        sa.Column("min_execution_time", sa.Float(), nullable=True),
        sa.Column("max_execution_time", sa.Float(), nullable=True),
        sa.Column("avg_queue_time", sa.Float(), nullable=True),
        # 成功率
        sa.Column("success_rate", sa.Float(), nullable=True),
        # 错误统计
        sa.Column("error_types", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        # 时间戳
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.text("now()")),
    )
    # Indexes for skill_metrics
    op.create_index("idx_skill_metrics_skill_id", "skill_metrics", ["skill_id"])
    op.create_index("idx_metric_skill_period", "skill_metrics", ["skill_id", "period_start"])
    op.create_index("idx_metric_created", "skill_metrics", ["created_at"])

    # ── skill_workflows ───────────────────────────────────────────────────────
    op.create_table(
        "skill_workflows",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        # 工作流标识
        sa.Column("workflow_id", sa.String(100), unique=True, nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        # 工作流定义
        sa.Column("workflow_definition", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("parameters", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        # 状态
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'draft'::character varying")),
        # 执行统计
        sa.Column("execution_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        # 元数据
        sa.Column("author", sa.String(100), nullable=True),
        sa.Column("tags", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("version", sa.String(20), nullable=False, server_default=sa.text("'1.0.0'::character varying")),
        # 时间戳
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.text("now()")),
        sa.Column("last_executed_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Indexes for skill_workflows
    op.create_index("idx_skill_workflows_workflow_id", "skill_workflows", ["workflow_id"], unique=True)
    op.create_index("idx_workflow_status", "skill_workflows", ["status"])
    op.create_index("idx_workflow_created", "skill_workflows", ["created_at"])


def downgrade() -> None:
    op.drop_table("skill_workflows")
    op.drop_table("skill_metrics")
    op.drop_table("skill_executions")
    op.drop_table("skill_definitions")
