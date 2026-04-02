-- Add equity_snapshot_interval to replay_sessions for configurable snapshot granularity

-- Add equity_snapshot_interval column with default 3600 (1 hour)
ALTER TABLE replay_sessions ADD COLUMN IF NOT EXISTS equity_snapshot_interval INTEGER NOT NULL DEFAULT 3600;

-- Add comment for documentation
COMMENT ON COLUMN replay_sessions.equity_snapshot_interval IS '权益快照间隔（秒），范围：60-14400，默认3600（1小时）';
