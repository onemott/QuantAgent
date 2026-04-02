-- Migration: Add paper_account_replay table for session-isolated replay accounts
-- Date: 2026-03-25
-- Description: Each historical replay session gets its own independent balance,
--             completely separate from the global PaperAccount(id=1) used by live paper trading.

-- Create per-session replay account table
CREATE TABLE IF NOT EXISTS paper_account_replay (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(64) UNIQUE NOT NULL,
    total_usdt NUMERIC(20, 8) NOT NULL DEFAULT 0,
    initial_capital NUMERIC(20, 8) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Index on session_id for fast lookups
CREATE INDEX IF NOT EXISTS idx_paper_account_replay_session_id
ON paper_account_replay(session_id);

-- EquitySnapshot table: add initial_capital column for replay PnL calculations
ALTER TABLE equity_snapshots
ADD COLUMN IF NOT EXISTS initial_capital NUMERIC(20, 8);
