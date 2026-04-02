-- ============================================================
-- 09_analytics_data_tagging.sql
-- Adds data_source, params_hash, backtest_id, and metrics columns
-- ============================================================

-- 1. data_source column on backtest_results (REAL/PAPER/BACKTEST/REPLAY/MOCK)
ALTER TABLE backtest_results ADD COLUMN IF NOT EXISTS data_source VARCHAR(20) NOT NULL DEFAULT 'BACKTEST';

-- 2. data_source column on paper_trades
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS data_source VARCHAR(20) NOT NULL DEFAULT 'PAPER';

-- 3. data_source column on equity_snapshots
ALTER TABLE equity_snapshots ADD COLUMN IF NOT EXISTS data_source VARCHAR(20) NOT NULL DEFAULT 'PAPER';

-- 4. data_source column on replay_sessions
ALTER TABLE replay_sessions ADD COLUMN IF NOT EXISTS data_source VARCHAR(20) NOT NULL DEFAULT 'REPLAY';

-- 5. params_hash on backtest_results (for matching with replay sessions)
ALTER TABLE backtest_results ADD COLUMN IF NOT EXISTS params_hash VARCHAR(64);

-- 6. params_hash on replay_sessions
ALTER TABLE replay_sessions ADD COLUMN IF NOT EXISTS params_hash VARCHAR(64);

-- 7. backtest_id FK on replay_sessions (links replay to its matching backtest)
ALTER TABLE replay_sessions ADD COLUMN IF NOT EXISTS backtest_id INTEGER REFERENCES backtest_results(id) ON DELETE SET NULL;

-- 8. metrics JSONB on replay_sessions (stores computed performance metrics)
ALTER TABLE replay_sessions ADD COLUMN IF NOT EXISTS metrics JSONB DEFAULT '{}';

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_backtest_data_source ON backtest_results(data_source);
CREATE INDEX IF NOT EXISTS idx_paper_trades_data_source ON paper_trades(data_source);
CREATE INDEX IF NOT EXISTS idx_equity_snapshots_data_source ON equity_snapshots(data_source);
CREATE INDEX IF NOT EXISTS idx_replay_sessions_backtest ON replay_sessions(backtest_id);
CREATE INDEX IF NOT EXISTS idx_replay_sessions_params_hash ON replay_sessions(params_hash);
CREATE INDEX IF NOT EXISTS idx_backtest_params_hash ON backtest_results(params_hash);
