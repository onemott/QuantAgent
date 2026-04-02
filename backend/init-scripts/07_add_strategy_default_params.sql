-- 策略默认参数持久化表
-- 用于存储用户优化或手动调整后的策略默认参数

CREATE TABLE IF NOT EXISTS strategy_default_params (
    id SERIAL PRIMARY KEY,
    strategy_type VARCHAR(50) NOT NULL,      -- 策略类型: ma, rsi, boll, macd, etc.
    param_key VARCHAR(100) NOT NULL,          -- 参数键: fast_period, rsi_period, etc.
    param_value FLOAT NOT NULL,              -- 参数值
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_by VARCHAR(100) DEFAULT 'system', -- 更新来源: optimization, manual, etc.
    UNIQUE(strategy_type, param_key)         -- 每个策略的每个参数唯一
);

-- 创建索引加速查询
CREATE INDEX IF NOT EXISTS idx_strategy_params_type ON strategy_default_params(strategy_type);

-- 策略参数更新历史表（可选，用于审计）
CREATE TABLE IF NOT EXISTS strategy_param_history (
    id SERIAL PRIMARY KEY,
    strategy_type VARCHAR(50) NOT NULL,
    param_key VARCHAR(100) NOT NULL,
    old_value FLOAT,
    new_value FLOAT NOT NULL,
    changed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    changed_by VARCHAR(100) DEFAULT 'system',
    reason VARCHAR(500)                        -- 变更原因: optimization, manual_adjustment, etc.
);

CREATE INDEX IF NOT EXISTS idx_param_history_type ON strategy_param_history(strategy_type);

-- 添加注释
COMMENT ON TABLE strategy_default_params IS '存储策略的默认参数值，支持优化后自动同步到回测/回放页面';
COMMENT ON COLUMN strategy_default_params.updated_by IS '更新来源: optimization(优化保存), manual_backtest(回测调整), manual_replay(回放调整)';
