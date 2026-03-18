-- Add Replay support to database schema

-- 1. Create replay_sessions table
CREATE TABLE IF NOT EXISTS replay_sessions (
    id SERIAL PRIMARY KEY,
    replay_session_id VARCHAR(50) NOT NULL UNIQUE,
    strategy_id INTEGER NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    start_time TIMESTAMP WITH TIME ZONE NOT NULL,
    end_time TIMESTAMP WITH TIME ZONE NOT NULL,
    speed INTEGER NOT NULL DEFAULT 1,
    initial_capital FLOAT NOT NULL DEFAULT 100000.0,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    current_timestamp TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_replay_session_id ON replay_sessions(replay_session_id);
CREATE INDEX IF NOT EXISTS idx_replay_strategy ON replay_sessions(strategy_id);

-- 2. Add mode and session_id to paper_trades table
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS mode VARCHAR(20) NOT NULL DEFAULT 'paper';
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS session_id VARCHAR(50);

-- 3. Add index for session-based queries
CREATE INDEX IF NOT EXISTS idx_paper_trades_session ON paper_trades(session_id);
CREATE INDEX IF NOT EXISTS idx_paper_trades_mode ON paper_trades(mode);
