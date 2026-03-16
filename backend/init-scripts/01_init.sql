-- QuantAgent OS - PostgreSQL Schema Initialization
-- Executed automatically by Docker on first container startup

-- ============================================================
-- Paper Trading Account
-- ============================================================
CREATE TABLE IF NOT EXISTS paper_account (
    id          SERIAL PRIMARY KEY,
    total_usdt  NUMERIC(20, 8) NOT NULL DEFAULT 100000.0,
    updated_at  TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

-- Insert default account (only if not exists)
INSERT INTO paper_account (id, total_usdt) VALUES (1, 100000.0)
ON CONFLICT (id) DO NOTHING;

-- ============================================================
-- Paper Trading Positions
-- ============================================================
CREATE TABLE IF NOT EXISTS paper_positions (
    symbol      VARCHAR(20)    NOT NULL PRIMARY KEY,
    quantity    NUMERIC(20, 8) NOT NULL DEFAULT 0,
    avg_price   NUMERIC(20, 8) NOT NULL DEFAULT 0,
    updated_at  TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

-- ============================================================
-- Paper Trading Orders / Trade History
-- ============================================================
CREATE TABLE IF NOT EXISTS paper_trades (
    id          SERIAL         PRIMARY KEY,
    symbol      VARCHAR(20)    NOT NULL,
    side        VARCHAR(4)     NOT NULL CHECK (side IN ('BUY', 'SELL')),
    order_type  VARCHAR(10)    NOT NULL DEFAULT 'MARKET',
    quantity    NUMERIC(20, 8) NOT NULL,
    price       NUMERIC(20, 8) NOT NULL,
    fee         NUMERIC(20, 8) NOT NULL DEFAULT 0,
    pnl         NUMERIC(20, 8),          -- NULL for BUY orders, set on SELL
    status      VARCHAR(10)    NOT NULL DEFAULT 'FILLED',
    created_at  TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_paper_trades_symbol  ON paper_trades (symbol);
CREATE INDEX IF NOT EXISTS idx_paper_trades_created ON paper_trades (created_at DESC);

-- ============================================================
-- Backtest Results
-- ============================================================
CREATE TABLE IF NOT EXISTS backtest_results (
    id              SERIAL         PRIMARY KEY,
    strategy_type   VARCHAR(20)    NOT NULL,  -- ma, rsi, boll
    symbol          VARCHAR(20)    NOT NULL,
    interval        VARCHAR(5)     NOT NULL,
    params          JSONB          NOT NULL DEFAULT '{}',
    metrics         JSONB          NOT NULL DEFAULT '{}',
    equity_curve    JSONB          NOT NULL DEFAULT '[]',  -- [{t: timestamp, v: value}, ...]
    trades_summary  JSONB          NOT NULL DEFAULT '[]',  -- first 50 trades
    created_at      TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_backtest_created ON backtest_results (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_backtest_strategy ON backtest_results (strategy_type, symbol);
