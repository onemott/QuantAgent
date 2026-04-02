-- Add session_id to equity_snapshots for historical replay isolation

-- Add session_id column
ALTER TABLE equity_snapshots ADD COLUMN IF NOT EXISTS session_id VARCHAR(50);

-- Add index for session-based queries
CREATE INDEX IF NOT EXISTS idx_equity_session ON equity_snapshots(session_id);
