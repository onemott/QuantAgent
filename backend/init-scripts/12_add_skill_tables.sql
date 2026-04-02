-- Add Skill system tables for the Skill framework
-- Creates 4 tables: skill_definitions, skill_executions, skill_metrics, skill_workflows

-- ═══════════════════════════════════════════════════════════════════════════
-- skill_definitions: Stores skill metadata, schemas, and configurations
-- ═══════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS skill_definitions (
    id SERIAL PRIMARY KEY,
    
    -- Skill标识
    skill_id VARCHAR(100) UNIQUE NOT NULL,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    
    -- Skill类型和分类
    skill_type VARCHAR(50) NOT NULL,
    category VARCHAR(50),
    
    -- 版本信息
    version VARCHAR(20) NOT NULL DEFAULT '1.0.0',
    status VARCHAR(20) NOT NULL DEFAULT 'active',  -- active, inactive, deprecated
    
    -- 配置和参数
    input_schema JSONB NOT NULL DEFAULT '{}',
    output_schema JSONB NOT NULL DEFAULT '{}',
    parameters JSONB NOT NULL DEFAULT '{}',
    dependencies JSONB NOT NULL DEFAULT '[]',  -- 依赖库列表
    
    -- 执行配置
    timeout_seconds INTEGER,
    max_retries INTEGER NOT NULL DEFAULT 3,
    concurrency_limit INTEGER NOT NULL DEFAULT 1,
    
    -- 实现信息
    implementation_path VARCHAR(500),
    code_content TEXT,
    
    -- 元数据
    author VARCHAR(100),
    tags JSONB NOT NULL DEFAULT '[]',
    
    -- 性能统计
    execution_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    avg_execution_time FLOAT,
    
    -- 时间戳
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE,
    last_executed_at TIMESTAMP WITH TIME ZONE
);

-- Indexes for skill_definitions
CREATE INDEX IF NOT EXISTS idx_skill_definitions_skill_id ON skill_definitions (skill_id);
CREATE INDEX IF NOT EXISTS idx_skill_type_status ON skill_definitions (skill_type, status);
CREATE INDEX IF NOT EXISTS idx_skill_created ON skill_definitions (created_at);
CREATE INDEX IF NOT EXISTS idx_skill_author ON skill_definitions (author);

-- Comments for skill_definitions
COMMENT ON TABLE skill_definitions IS 'Skill定义表：存储技能的元数据、配置和实现信息';
COMMENT ON COLUMN skill_definitions.skill_id IS 'Skill唯一标识符';
COMMENT ON COLUMN skill_definitions.name IS 'Skill名称';
COMMENT ON COLUMN skill_definitions.description IS 'Skill描述';
COMMENT ON COLUMN skill_definitions.skill_type IS 'Skill类型（如 strategy_generator, optimization_evaluator）';
COMMENT ON COLUMN skill_definitions.category IS 'Skill分类';
COMMENT ON COLUMN skill_definitions.version IS '版本号，默认1.0.0';
COMMENT ON COLUMN skill_definitions.status IS '状态：active（活跃）, inactive（停用）, deprecated（已废弃）';
COMMENT ON COLUMN skill_definitions.input_schema IS '输入参数JSON Schema';
COMMENT ON COLUMN skill_definitions.output_schema IS '输出结果JSON Schema';
COMMENT ON COLUMN skill_definitions.parameters IS '默认参数配置';
COMMENT ON COLUMN skill_definitions.dependencies IS '依赖库列表';
COMMENT ON COLUMN skill_definitions.timeout_seconds IS '执行超时时间（秒）';
COMMENT ON COLUMN skill_definitions.max_retries IS '最大重试次数，默认3';
COMMENT ON COLUMN skill_definitions.concurrency_limit IS '并发限制，默认1';
COMMENT ON COLUMN skill_definitions.implementation_path IS '实现模块路径';
COMMENT ON COLUMN skill_definitions.code_content IS '代码内容（可选）';
COMMENT ON COLUMN skill_definitions.author IS '作者';
COMMENT ON COLUMN skill_definitions.tags IS '标签列表';
COMMENT ON COLUMN skill_definitions.execution_count IS '总执行次数';
COMMENT ON COLUMN skill_definitions.success_count IS '成功执行次数';
COMMENT ON COLUMN skill_definitions.avg_execution_time IS '平均执行时间（秒）';
COMMENT ON COLUMN skill_definitions.created_at IS '创建时间';
COMMENT ON COLUMN skill_definitions.updated_at IS '更新时间';
COMMENT ON COLUMN skill_definitions.last_executed_at IS '最后执行时间';

-- ═══════════════════════════════════════════════════════════════════════════
-- skill_executions: Records individual skill execution history
-- ═══════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS skill_executions (
    id SERIAL PRIMARY KEY,
    
    -- 执行标识
    execution_id VARCHAR(100) UNIQUE NOT NULL,
    skill_id VARCHAR(100) NOT NULL,
    skill_version VARCHAR(20) NOT NULL,
    
    -- 执行状态
    status VARCHAR(20) NOT NULL,  -- pending, running, completed, failed, cancelled
    success BOOLEAN NOT NULL,
    
    -- 输入输出
    inputs JSONB NOT NULL DEFAULT '{}',
    inputs_hash VARCHAR(64),  -- 输入哈希，用于去重
    parameters JSONB NOT NULL DEFAULT '{}',
    context JSONB,
    
    -- 结果
    result_data JSONB,
    error_message TEXT,
    error_details JSONB,
    
    -- 性能指标
    execution_time FLOAT,  -- 执行时间（秒）
    queue_time FLOAT,  -- 排队时间（秒）
    
    -- 时间戳
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    
    -- 关联
    parent_execution_id VARCHAR(100),  -- 父执行ID，用于工作流
    workflow_id VARCHAR(100),  -- 所属工作流ID
    
    -- 元数据
    executed_by VARCHAR(100) DEFAULT 'system',
    execution_tags JSONB NOT NULL DEFAULT '[]'
);

-- Indexes for skill_executions
CREATE INDEX IF NOT EXISTS idx_skill_executions_execution_id ON skill_executions (execution_id);
CREATE INDEX IF NOT EXISTS idx_execution_skill ON skill_executions (skill_id);
CREATE INDEX IF NOT EXISTS idx_execution_status ON skill_executions (status);
CREATE INDEX IF NOT EXISTS idx_execution_created ON skill_executions (created_at);
CREATE INDEX IF NOT EXISTS idx_execution_hash ON skill_executions (inputs_hash);
CREATE INDEX IF NOT EXISTS idx_skill_executions_parent ON skill_executions (parent_execution_id);
CREATE INDEX IF NOT EXISTS idx_skill_executions_workflow ON skill_executions (workflow_id);

-- Comments for skill_executions
COMMENT ON TABLE skill_executions IS 'Skill执行记录表：记录每次执行的详细信息和结果';
COMMENT ON COLUMN skill_executions.execution_id IS '执行唯一标识符';
COMMENT ON COLUMN skill_executions.skill_id IS '关联的Skill ID';
COMMENT ON COLUMN skill_executions.skill_version IS '执行时的Skill版本';
COMMENT ON COLUMN skill_executions.status IS '执行状态：pending, running, completed, failed, cancelled';
COMMENT ON COLUMN skill_executions.success IS '是否执行成功';
COMMENT ON COLUMN skill_executions.inputs IS '输入参数';
COMMENT ON COLUMN skill_executions.inputs_hash IS '输入参数哈希值，用于幂等去重';
COMMENT ON COLUMN skill_executions.parameters IS '执行参数配置';
COMMENT ON COLUMN skill_executions.context IS '执行上下文信息';
COMMENT ON COLUMN skill_executions.result_data IS '执行结果数据';
COMMENT ON COLUMN skill_executions.error_message IS '错误信息';
COMMENT ON COLUMN skill_executions.error_details IS '错误详情';
COMMENT ON COLUMN skill_executions.execution_time IS '执行时间（秒）';
COMMENT ON COLUMN skill_executions.queue_time IS '排队等待时间（秒）';
COMMENT ON COLUMN skill_executions.created_at IS '创建时间';
COMMENT ON COLUMN skill_executions.started_at IS '开始执行时间';
COMMENT ON COLUMN skill_executions.completed_at IS '完成时间';
COMMENT ON COLUMN skill_executions.parent_execution_id IS '父执行ID，用于工作流嵌套';
COMMENT ON COLUMN skill_executions.workflow_id IS '所属工作流ID';
COMMENT ON COLUMN skill_executions.executed_by IS '执行者';
COMMENT ON COLUMN skill_executions.execution_tags IS '执行标签';

-- ═══════════════════════════════════════════════════════════════════════════
-- skill_metrics: Aggregates performance metrics per skill over time periods
-- ═══════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS skill_metrics (
    id SERIAL PRIMARY KEY,
    
    -- 关联
    skill_id VARCHAR(100) NOT NULL,
    
    -- 统计周期
    period_start TIMESTAMP WITH TIME ZONE NOT NULL,
    period_end TIMESTAMP WITH TIME ZONE NOT NULL,
    period_type VARCHAR(20) NOT NULL,  -- hourly, daily, weekly, monthly
    
    -- 执行统计
    total_executions INTEGER NOT NULL DEFAULT 0,
    successful_executions INTEGER NOT NULL DEFAULT 0,
    failed_executions INTEGER NOT NULL DEFAULT 0,
    cancelled_executions INTEGER NOT NULL DEFAULT 0,
    
    -- 性能指标
    avg_execution_time FLOAT,
    min_execution_time FLOAT,
    max_execution_time FLOAT,
    avg_queue_time FLOAT,
    
    -- 成功率
    success_rate FLOAT,
    
    -- 错误统计
    error_types JSONB NOT NULL DEFAULT '{}',  -- 错误类型分布
    
    -- 时间戳
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE
);

-- Indexes for skill_metrics
CREATE INDEX IF NOT EXISTS idx_skill_metrics_skill_id ON skill_metrics (skill_id);
CREATE INDEX IF NOT EXISTS idx_metric_skill_period ON skill_metrics (skill_id, period_start);
CREATE INDEX IF NOT EXISTS idx_metric_created ON skill_metrics (created_at);

-- Comments for skill_metrics
COMMENT ON TABLE skill_metrics IS 'Skill性能指标表：聚合统计各时间段内的执行性能';
COMMENT ON COLUMN skill_metrics.skill_id IS '关联的Skill ID';
COMMENT ON COLUMN skill_metrics.period_start IS '统计周期开始时间';
COMMENT ON COLUMN skill_metrics.period_end IS '统计周期结束时间';
COMMENT ON COLUMN skill_metrics.period_type IS '周期类型：hourly, daily, weekly, monthly';
COMMENT ON COLUMN skill_metrics.total_executions IS '总执行次数';
COMMENT ON COLUMN skill_metrics.successful_executions IS '成功执行次数';
COMMENT ON COLUMN skill_metrics.failed_executions IS '失败执行次数';
COMMENT ON COLUMN skill_metrics.cancelled_executions IS '取消执行次数';
COMMENT ON COLUMN skill_metrics.avg_execution_time IS '平均执行时间（秒）';
COMMENT ON COLUMN skill_metrics.min_execution_time IS '最小执行时间（秒）';
COMMENT ON COLUMN skill_metrics.max_execution_time IS '最大执行时间（秒）';
COMMENT ON COLUMN skill_metrics.avg_queue_time IS '平均排队时间（秒）';
COMMENT ON COLUMN skill_metrics.success_rate IS '成功率（0-1）';
COMMENT ON COLUMN skill_metrics.error_types IS '错误类型分布统计';
COMMENT ON COLUMN skill_metrics.created_at IS '创建时间';
COMMENT ON COLUMN skill_metrics.updated_at IS '更新时间';

-- ═══════════════════════════════════════════════════════════════════════════
-- skill_workflows: Defines multi-step skill workflows
-- ═══════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS skill_workflows (
    id SERIAL PRIMARY KEY,
    
    -- 工作流标识
    workflow_id VARCHAR(100) UNIQUE NOT NULL,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    
    -- 工作流定义
    workflow_definition JSONB NOT NULL DEFAULT '{}',  -- 工作流步骤定义
    parameters JSONB NOT NULL DEFAULT '{}',
    
    -- 状态
    status VARCHAR(20) NOT NULL DEFAULT 'draft',  -- draft, active, inactive
    
    -- 执行统计
    execution_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    
    -- 元数据
    author VARCHAR(100),
    tags JSONB NOT NULL DEFAULT '[]',
    version VARCHAR(20) NOT NULL DEFAULT '1.0.0',
    
    -- 时间戳
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE,
    last_executed_at TIMESTAMP WITH TIME ZONE
);

-- Indexes for skill_workflows
CREATE INDEX IF NOT EXISTS idx_skill_workflows_workflow_id ON skill_workflows (workflow_id);
CREATE INDEX IF NOT EXISTS idx_workflow_status ON skill_workflows (status);
CREATE INDEX IF NOT EXISTS idx_workflow_created ON skill_workflows (created_at);

-- Comments for skill_workflows
COMMENT ON TABLE skill_workflows IS 'Skill工作流表：定义多步骤的技能编排流程';
COMMENT ON COLUMN skill_workflows.workflow_id IS '工作流唯一标识符';
COMMENT ON COLUMN skill_workflows.name IS '工作流名称';
COMMENT ON COLUMN skill_workflows.description IS '工作流描述';
COMMENT ON COLUMN skill_workflows.workflow_definition IS '工作流步骤定义（JSON）';
COMMENT ON COLUMN skill_workflows.parameters IS '工作流参数配置';
COMMENT ON COLUMN skill_workflows.status IS '状态：draft（草稿）, active（活跃）, inactive（停用）';
COMMENT ON COLUMN skill_workflows.execution_count IS '总执行次数';
COMMENT ON COLUMN skill_workflows.success_count IS '成功执行次数';
COMMENT ON COLUMN skill_workflows.author IS '作者';
COMMENT ON COLUMN skill_workflows.tags IS '标签列表';
COMMENT ON COLUMN skill_workflows.version IS '版本号';
COMMENT ON COLUMN skill_workflows.created_at IS '创建时间';
COMMENT ON COLUMN skill_workflows.updated_at IS '更新时间';
COMMENT ON COLUMN skill_workflows.last_executed_at IS '最后执行时间';
