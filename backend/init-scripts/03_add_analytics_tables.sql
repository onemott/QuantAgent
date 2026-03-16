-- QuantAgent OS - Analytics Tables Migration
-- Adds trade_pairs, equity_snapshots, performance_metrics tables

-- ============================================================
-- Trade Pairs (Order Pairing / Entry-Exit Linking)
-- ============================================================
CREATE TABLE IF NOT EXISTS trade_pairs (
    id                  SERIAL PRIMARY KEY,
    pair_id             VARCHAR(36)    NOT NULL,
    symbol              VARCHAR(20)    NOT NULL,

    -- Linked trade IDs
    entry_trade_id      INTEGER        NOT NULL REFERENCES paper_trades(id),
    exit_trade_id       INTEGER        REFERENCES paper_trades(id),

    -- Pair timing
    entry_time          TIMESTAMPTZ    NOT NULL,
    exit_time           TIMESTAMPTZ,

    entry_price         NUMERIC(20, 8) NOT NULL,
    exit_price          NUMERIC(20, 8),

    quantity            NUMERIC(20, 8) NOT NULL,
    side                VARCHAR(5)     NOT NULL,  -- LONG or SHORT

    -- Holding costs (fees + funding)
    holding_costs       NUMERIC(20, 8) NOT NULL DEFAULT 0,

    -- Status & P&L
    status              VARCHAR(10)    NOT NULL DEFAULT 'OPEN',  -- OPEN | CLOSED
    pnl                 NUMERIC(20, 8),
    pnl_pct             NUMERIC(10, 4),

    -- Holding duration (hours)
    holding_hours       NUMERIC(10, 2),

    created_at          TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trade_pairs_pair   ON trade_pairs (pair_id);
CREATE INDEX IF NOT EXISTS idx_trade_pairs_symbol ON trade_pairs (symbol);
CREATE INDEX IF NOT EXISTS idx_trade_pairs_status ON trade_pairs (status);

-- ============================================================
-- Equity Snapshots (Hourly equity curve recording)
-- ============================================================
CREATE TABLE IF NOT EXISTS equity_snapshots (
    id              SERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    total_equity    NUMERIC(20, 8) NOT NULL,
    cash_balance    NUMERIC(20, 8) NOT NULL,
    position_value  NUMERIC(20, 8) NOT NULL DEFAULT 0,
    daily_pnl       NUMERIC(20, 8) DEFAULT 0,
    daily_return    NUMERIC(10, 6) DEFAULT 0,
    drawdown        NUMERIC(10, 6) DEFAULT 0,
    created_at      TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_equity_timestamp ON equity_snapshots (timestamp);

-- ============================================================
-- Performance Metrics (Aggregated stats per period)
-- ============================================================
CREATE TABLE IF NOT EXISTS performance_metrics (
    id                      SERIAL PRIMARY KEY,
    period                  VARCHAR(20)    NOT NULL,  -- daily | weekly | monthly | all_time
    start_date              TIMESTAMPTZ    NOT NULL,
    end_date                TIMESTAMPTZ    NOT NULL,

    -- Basic metrics
    initial_equity          NUMERIC(20, 8) NOT NULL,
    final_equity            NUMERIC(20, 8) NOT NULL,
    total_return            NUMERIC(10, 4) NOT NULL DEFAULT 0,
    total_trades            INTEGER        NOT NULL DEFAULT 0,
    winning_trades          INTEGER        NOT NULL DEFAULT 0,
    losing_trades           INTEGER        NOT NULL DEFAULT 0,

    -- Risk metrics
    max_drawdown            NUMERIC(10, 4) NOT NULL DEFAULT 0,
    max_drawdown_pct        NUMERIC(10, 4) NOT NULL DEFAULT 0,
    volatility              NUMERIC(10, 4) NOT NULL DEFAULT 0,

    -- Return metrics
    annualized_return       NUMERIC(10, 4) NOT NULL DEFAULT 0,
    sharpe_ratio            NUMERIC(10, 4),
    sortino_ratio           NUMERIC(10, 4),
    calmar_ratio            NUMERIC(10, 4),

    -- Trade metrics
    win_rate                NUMERIC(10, 4) NOT NULL DEFAULT 0,
    profit_factor           NUMERIC(10, 4),
    avg_holding_hours       NUMERIC(10, 2),
    max_consecutive_wins    INTEGER DEFAULT 0,
    max_consecutive_losses  INTEGER DEFAULT 0,

    created_at              TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_perf_period ON performance_metrics (period);

-- ============================================================
-- Add benchmark_price and funding_fee columns to paper_trades if missing
-- ============================================================
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'paper_trades' AND column_name = 'benchmark_price'
    ) THEN
        ALTER TABLE paper_trades ADD COLUMN benchmark_price NUMERIC(20, 8);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'paper_trades' AND column_name = 'funding_fee'
    ) THEN
        ALTER TABLE paper_trades ADD COLUMN funding_fee NUMERIC(20, 8) NOT NULL DEFAULT 0;
    END IF;
END
$$;
