-- Add saved/deleted support for replay sessions
-- Date: 2026-03-19

-- 1. Add is_saved field to replay_sessions table
ALTER TABLE replay_sessions ADD COLUMN IF NOT EXISTS is_saved BOOLEAN NOT NULL DEFAULT FALSE;

-- 2. Add updated_at field for tracking modifications
ALTER TABLE replay_sessions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE;

-- 3. Create index for efficient saved records queries
CREATE INDEX IF NOT EXISTS idx_replay_sessions_saved ON replay_sessions(is_saved) WHERE is_saved = TRUE;

-- 4. Create index for status queries
CREATE INDEX IF NOT EXISTS idx_replay_sessions_status ON replay_sessions(status);

-- 5. Create index for created_at for sorting
CREATE INDEX IF NOT EXISTS idx_replay_sessions_created ON replay_sessions(created_at DESC);
