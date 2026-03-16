-- QuantAgent OS - Idempotency Support Migration
-- Adds client_order_id column and unique index to paper_trades for idempotency

-- Add client_order_id column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'paper_trades' AND column_name = 'client_order_id'
    ) THEN
        ALTER TABLE paper_trades ADD COLUMN client_order_id VARCHAR(50);
    END IF;
END
$$;

-- Create unique index for idempotency
CREATE UNIQUE INDEX IF NOT EXISTS idx_paper_trades_client_order_id 
ON paper_trades (client_order_id) 
WHERE client_order_id IS NOT NULL;
