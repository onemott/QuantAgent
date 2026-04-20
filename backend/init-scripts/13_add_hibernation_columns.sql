-- Add hibernation and revival columns to selection_history for strategy sleep/revive mechanism

-- Add hibernating_strategy_ids column
ALTER TABLE selection_history ADD COLUMN IF NOT EXISTS hibernating_strategy_ids JSONB DEFAULT NULL;

-- Add revived_strategy_ids column
ALTER TABLE selection_history ADD COLUMN IF NOT EXISTS revived_strategy_ids JSONB DEFAULT NULL;

-- Add revival_reasons column
ALTER TABLE selection_history ADD COLUMN IF NOT EXISTS revival_reasons JSONB DEFAULT NULL;

-- Add comments for documentation
COMMENT ON COLUMN selection_history.hibernating_strategy_ids IS '当前处于休眠状态的策略ID列表';
COMMENT ON COLUMN selection_history.revived_strategy_ids IS '本轮被复活的策略ID列表';
COMMENT ON COLUMN selection_history.revival_reasons IS '复活原因字典';
