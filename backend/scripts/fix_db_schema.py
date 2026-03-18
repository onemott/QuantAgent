
import asyncio
import asyncpg
import logging
import sys
import os

# Add backend to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from app.core.config import settings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def fix_schema():
    logger.info(f"Connecting to database: {settings.DATABASE_URL}")
    
    # Parse DATABASE_URL
    # postgresql+asyncpg://user:pass@host:port/db
    # We need to convert it to asyncpg format or pass params directly
    # Simple parsing for this specific format:
    import re
    # Replace localhost with 127.0.0.1 to avoid IPv6 issues on Windows
    db_url = settings.DATABASE_URL.replace("localhost", "127.0.0.1")
    logger.info(f"Using DB URL: {db_url}")
    
    match = re.match(r"postgresql\+asyncpg://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)", db_url)
    if not match:
        logger.error("Could not parse DATABASE_URL")
        return

    user, password, host, port, database = match.groups()
    
    try:
        conn = await asyncpg.connect(
            user=user,
            password=password,
            host=host,
            port=port,
            database=database
        )
        
        logger.info("Connected. Attempting to enable pgvector extension...")
        try:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            logger.info("pgvector extension enabled.")
        except Exception as e:
            logger.warning(f"Could not enable pgvector: {e}. Embedding column might fail.")

        logger.info("Checking 'agent_memories' table...")
        
        # Check if column exists
        row = await conn.fetchrow("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='agent_memories' AND column_name='reasoning_summary';
        """)
        
        if row:
            logger.info("Column 'reasoning_summary' already exists.")
        else:
            logger.info("Adding column 'reasoning_summary'...")
            await conn.execute("ALTER TABLE agent_memories ADD COLUMN reasoning_summary TEXT;")
            logger.info("Column added successfully.")

        # Check for other missing columns
        columns_to_check = [
            ("action", "VARCHAR(20)"),
            ("signal", "VARCHAR(20)"),
            ("confidence", "FLOAT"),
            ("entry_price", "FLOAT"),
            ("outcome_pnl", "FLOAT"),
            # vector extension might be needed for this, assume vector type exists or use float[]
            # But let's check if vector extension is enabled first. 
            # If not, maybe skip or use generic array?
            # For now let's try adding it as vector(1536) if possible, or skip if complex.
            # actually pgvector might not be installed in the DB.
            # Let's try adding it.
            ("market_state_embedding", "vector(1536)") 
        ]

        for col_name, col_type in columns_to_check:
             row = await conn.fetchrow(f"""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='agent_memories' AND column_name='{col_name}';
            """)
             if not row:
                 logger.info(f"Adding column '{col_name}'...")
                 try:
                    await conn.execute(f"ALTER TABLE agent_memories ADD COLUMN {col_name} {col_type};")
                    logger.info(f"Column '{col_name}' added.")
                 except Exception as e:
                     logger.error(f"Failed to add column {col_name}: {e}")
        
        # Check 'paper_positions' table for missing columns
        logger.info("Checking 'paper_positions' table...")
        pos_columns = [
            ("strategy_id", "VARCHAR(30)"),
            ("leverage", "INTEGER DEFAULT 1"),
            ("liquidation_price", "NUMERIC(20, 8)")
        ]
        for col_name, col_type in pos_columns:
            row = await conn.fetchrow(f"""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='paper_positions' AND column_name='{col_name}';
            """)
            if not row:
                logger.info(f"Adding column '{col_name}' to 'paper_positions'...")
                try:
                    await conn.execute(f"ALTER TABLE paper_positions ADD COLUMN {col_name} {col_type};")
                    logger.info(f"Column '{col_name}' added successfully.")
                except Exception as e:
                    logger.error(f"Failed to add column {col_name} to 'paper_positions': {e}")

        # Check 'paper_trades' table
        logger.info("Checking 'paper_trades' table...")
        trade_columns = [
            ("strategy_id", "VARCHAR(30)"),
            ("client_order_id", "VARCHAR(50)"),
            ("benchmark_price", "NUMERIC(20, 8)")
        ]
        for col_name, col_type in trade_columns:
            row = await conn.fetchrow(f"""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='paper_trades' AND column_name='{col_name}';
            """)
            if not row:
                logger.info(f"Adding column '{col_name}' to 'paper_trades'...")
                try:
                    await conn.execute(f"ALTER TABLE paper_trades ADD COLUMN {col_name} {col_type};")
                    logger.info(f"Column '{col_name}' added successfully.")
                except Exception as e:
                    logger.error(f"Failed to add column {col_name} to 'paper_trades': {e}")

        # Check 'trade_pairs' table
        logger.info("Checking 'trade_pairs' table...")
        pair_columns = [
            ("strategy_id", "VARCHAR(30)")
        ]
        for col_name, col_type in pair_columns:
            row = await conn.fetchrow(f"""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='trade_pairs' AND column_name='{col_name}';
            """)
            if not row:
                logger.info(f"Adding column '{col_name}' to 'trade_pairs'...")
                try:
                    await conn.execute(f"ALTER TABLE trade_pairs ADD COLUMN {col_name} {col_type};")
                    logger.info(f"Column '{col_name}' added successfully.")
                except Exception as e:
                    logger.error(f"Failed to add column {col_name} to 'trade_pairs': {e}")

        await conn.close()
        
    except Exception as e:
        logger.error(f"Error fixing schema: {e}")
        if "WinError 1225" in str(e) or "ConnectionRefusedError" in str(e):
             logger.error("\n[!] Connection refused. Please ensure:")
             logger.error("1. PostgreSQL service is running.")
             logger.error("2. PostgreSQL is listening on port 5432.")
             logger.error("3. If using Docker, ensure port 5432 is mapped to host.")
             logger.error(f"   Database URL: {settings.DATABASE_URL}")

if __name__ == "__main__":
    asyncio.run(fix_schema())
