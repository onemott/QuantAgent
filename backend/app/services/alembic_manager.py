"""
Programmatic Alembic migration management.

Provides async-safe wrappers around Alembic's upgrade/stamp operations
so they can be called from the FastAPI lifespan or CLI scripts.

Usage:
    # In FastAPI lifespan (main.py):
    from app.services.alembic_manager import alembic_manager
    await alembic_manager.upgrade_if_needed()

    # CLI:
    python scripts/run_migrations.py upgrade
    python scripts/run_migrations.py stamp 001
    python scripts/run_migrations.py history
"""

import logging
from pathlib import Path
from typing import Optional

from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

# Root of the backend project (where alembic.ini lives)
ALEMBIC_INI = Path(__file__).parent.parent.parent / "alembic.ini"
ALEMBIC_DIR = ALEMBIC_INI.parent / "migrations"


class AlembicManager:
    """Thread-safe Alembic migration manager for async contexts."""

    def __init__(self, alembic_ini: Path = ALEMBIC_INI):
        self.alembic_ini = alembic_ini
        self._alembic_cfg: Optional[AlembicConfig] = None

    def _get_config(self) -> AlembicConfig:
        """Lazily create and cache the Alembic Config object."""
        if self._alembic_cfg is None:
            self._alembic_cfg = AlembicConfig(str(self.alembic_ini))
            # Ensure the script location is set correctly
            self._alembic_cfg.set_main_option("script_location", str(ALEMBIC_DIR))
        return self._alembic_cfg

    async def upgrade_to_head(self, engine: AsyncEngine) -> None:
        """
        Run all pending Alembic migrations up to head.

        Args:
            engine: Async SQLAlchemy engine connected to the target database.
        """
        cfg = self._get_config()
        try:
            # Stamp current DB state as '001' baseline to prevent re-running
            # the baseline migration on fresh databases (we only create tables once).
            # After this, normal upgrade applies new migrations only.
            current_rev = await self._get_current_revision(engine)
            if current_rev is None:
                # No prior migrations applied — stamp baseline so it's not re-run,
                # then upgrade (no-op since baseline is already stamped).
                # Actually, we should run the baseline migration on a truly fresh DB.
                # Only stamp if the DB already has tables (i.e., was set up via init-scripts).
                tables_exist = await self._tables_exist(engine)
                if tables_exist:
                    logger.info("Tables exist (likely from init-scripts) — stamping baseline migration")
                    command.stamp(cfg, "001_initial_schema")
                else:
                    logger.info("No tables found — running baseline migration")
                    command.upgrade(cfg, "001")
            else:
                logger.info(f"Current migration revision: {current_rev} — running pending migrations")
                command.upgrade(cfg, "head")

        except Exception as e:
            logger.error(f"Alembic upgrade failed: {e}")
            raise

    async def stamp_revision(self, engine: AsyncEngine, revision: str) -> None:
        """
        Stamp the database at a given revision without running migrations.
        Used for transitioning existing databases to Alembic.

        Args:
            engine: Async SQLAlchemy engine.
            revision: Revision string (e.g., "001", "head", "base").
        """
        cfg = self._get_config()
        try:
            command.stamp(cfg, revision)
            logger.info(f"Database stamped at revision: {revision}")
        except Exception as e:
            logger.error(f"Alembic stamp failed: {e}")
            raise

    async def get_current_revision(self, engine: AsyncEngine) -> Optional[str]:
        """Get the current Alembic revision of the database."""
        return await self._get_current_revision(engine)

    async def get_pending_revisions(self, engine: AsyncEngine) -> list[str]:
        """Get list of revisions not yet applied."""
        cfg = self._get_config()
        from alembic.script import ScriptDirectory
        script = ScriptDirectory.from_config(cfg)

        current_rev = await self._get_current_revision(engine)
        pending = []
        for rev in script.walk_revisions("head", current_rev or "base"):
            if rev.revision != current_rev:
                pending.append(rev.revision)
        return pending

    # ─── Private helpers ────────────────────────────────────────────────────────

    async def _get_current_revision(self, engine: AsyncEngine) -> Optional[str]:
        """Query the alembic_version table for the current revision."""
        try:
            async with engine.connect() as conn:
                # Check if alembic_version table exists
                result = await conn.execute(
                    text("SELECT version_num FROM alembic_version LIMIT 1")
                )
                row = result.fetchone()
                return row[0] if row else None
        except Exception:
            # Table doesn't exist yet
            return None

    async def _tables_exist(self, engine: AsyncEngine) -> bool:
        """
        Check if any application tables exist.
        If true, the database was likely set up via init-scripts (not Alembic).
        """
        try:
            async with engine.connect() as conn:
                result = await conn.execute(
                    text("""
                        SELECT EXISTS (
                            SELECT FROM pg_tables
                            WHERE schemaname = 'public'
                            AND tablename IN ('paper_account', 'paper_trades')
                        )
                    """)
                )
                row = result.fetchone()
                return bool(row[0]) if row else False
        except Exception:
            return False


# Singleton instance
alembic_manager = AlembicManager()
