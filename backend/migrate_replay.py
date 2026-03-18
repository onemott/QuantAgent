
import asyncio
import logging
from sqlalchemy import text
from app.services.database import get_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def migrate():
    async with get_db() as session:
        # 1. Update replay_sessions table
        logger.info("Updating replay_sessions table...")
        try:
            await session.execute(text("ALTER TABLE replay_sessions ADD COLUMN IF NOT EXISTS strategy_type VARCHAR(20)"))
            await session.execute(text("ALTER TABLE replay_sessions ADD COLUMN IF NOT EXISTS params JSONB DEFAULT '{}'::jsonb"))
            logger.info("replay_sessions table updated.")
        except Exception as e:
            logger.error(f"Failed to update replay_sessions: {e}")

        # 2. Update paper_positions table
        logger.info("Updating paper_positions table...")
        try:
            # Drop old primary key and add new one with session_id
            # First check if id column exists (it's new)
            res = await session.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='paper_positions' AND column_name='id'"))
            if not res.scalar():
                logger.info("Adding id column and updating primary key for paper_positions...")
                await session.execute(text("ALTER TABLE paper_positions DROP CONSTRAINT IF EXISTS paper_positions_pkey"))
                await session.execute(text("ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS id SERIAL"))
                await session.execute(text("ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS session_id VARCHAR(50)"))
                await session.execute(text("ALTER TABLE paper_positions ADD PRIMARY KEY (id)"))
                await session.execute(text("CREATE INDEX IF NOT EXISTS idx_paper_positions_session ON paper_positions(session_id)"))
                logger.info("paper_positions table structure updated.")
            else:
                logger.info("paper_positions table already has id column.")
        except Exception as e:
            logger.error(f"Failed to update paper_positions: {e}")

        await session.commit()
    logger.info("Migration completed.")

if __name__ == "__main__":
    asyncio.run(migrate())
