-- Add columns for TCA (Transaction Cost Analysis)
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS benchmark_price NUMERIC(20, 8);
ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS funding_fee NUMERIC(20, 8) DEFAULT 0;
