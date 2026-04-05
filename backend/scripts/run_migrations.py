#!/usr/bin/env python
"""
Alembic migration CLI for QuantAgent OS.

Provides convenient commands for running database migrations.

Usage:
    # Run all pending migrations
    python scripts/run_migrations.py upgrade

    # Show current revision
    python scripts/run_migrations.py current

    # Show migration history
    python scripts/run_migrations.py history

    # Stamp baseline (for transitioning existing DBs from init-scripts to Alembic)
    python scripts/run_migrations.py stamp 001

    # Rollback one migration
    python scripts/run_migrations.py downgrade -1

    # Show pending migrations
    python scripts/run_migrations.py pending

    # Generate a new migration (requires DB connection for autogenerate)
    python scripts/run_migrations.py revision --autogenerate -m "add new column"

Examples:
    # First time setup on existing DB (already has init-scripts tables):
    python scripts/run_migrations.py stamp 001

    # Fresh DB — run baseline migration:
    python scripts/run_migrations.py upgrade

    # After code changes — generate and apply new migration:
    python scripts/run_migrations.py revision --autogenerate -m "add signal_type column"
    python scripts/run_migrations.py upgrade
"""

import asyncio
import sys
from pathlib import Path

# Ensure backend package is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory

from app.core.config import settings
from app.services.database import get_engine


ALEMBIC_INI = Path(__file__).parent.parent / "alembic.ini"
ALEMBIC_DIR = ALEMBIC_INI.parent / "migrations"


def get_alembic_config() -> AlembicConfig:
    cfg = AlembicConfig(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
    return cfg


async def cmd_current():
    engine = get_engine()
    from app.services.alembic_manager import alembic_manager
    rev = await alembic_manager.get_current_revision(engine)
    if rev:
        print(f"Current revision: {rev}")
    else:
        print("No migrations applied (unversioned database)")


async def cmd_history():
    cfg = get_alembic_config()
    script = ScriptDirectory.from_config(cfg)
    print("Migration history (oldest → newest):")
    # walk_revisions(base, head) — base is starting point, head is ending point.
    # "base" means "before first migration"; "heads" means "all current heads".
    for rev in script.walk_revisions("base", "heads"):
        prefix = "-> " if rev.is_head else "   "
        print(f"  {prefix}{rev.revision}  {rev.doc or '(no message)'}")


async def cmd_pending():
    cfg = get_alembic_config()
    script = ScriptDirectory.from_config(cfg)
    from app.services.alembic_manager import alembic_manager
    engine = get_engine()
    current_rev = await alembic_manager.get_current_revision(engine)
    pending = []
    # base=current_rev (or "base" if unversioned), head="heads"
    base = current_rev if current_rev else "base"
    for rev in script.walk_revisions(base, "heads"):
        if rev.revision != current_rev:
            pending.append(rev)
    if not pending:
        print("No pending migrations — database is up to date.")
    else:
        print("Pending migrations:")
        for rev in pending:
            print(f"  {rev.revision}  {rev.doc or '(no message)'}")


async def cmd_upgrade(revision: str = "head"):
    cfg = get_alembic_config()
    engine = get_engine()
    from app.services.alembic_manager import alembic_manager

    tables_exist = await alembic_manager._tables_exist(engine)
    current_rev = await alembic_manager.get_current_revision(engine)

    if current_rev is None and tables_exist:
        # DB has tables but no Alembic version — stamp baseline
        print("Tables detected (from init-scripts) — stamping baseline migration 001_initial_schema")
        command.stamp(cfg, "001_initial_schema")
        print("Baseline stamped. Run 'python scripts/run_migrations.py upgrade' to apply new migrations.")
    elif current_rev is None:
        # Fresh DB — run baseline
        print("Fresh database — running baseline migration...")
        command.upgrade(cfg, revision)
        print(f"Migrations applied: {revision}")
    else:
        print(f"Applying migrations up to {revision}...")
        command.upgrade(cfg, revision)
        print(f"Migrations applied: {revision}")


async def cmd_downgrade(revision: str):
    cfg = get_alembic_config()
    command.downgrade(cfg, revision)
    print(f"Downgraded to: {revision}")


async def cmd_stamp(revision: str):
    cfg = get_alembic_config()
    command.stamp(cfg, revision)
    print(f"Database stamped at: {revision}")


def cmd_revision(message: str, autogenerate: bool = False):
    cfg = get_alembic_config()
    kwargs = {}
    if autogenerate:
        kwargs["autogenerate"] = True
    command.revision(cfg, message=message or "auto-generated migration", **kwargs)
    print(f"Migration created{' with autogenerate' if autogenerate else ''}")


def cmd_merge(revision: str, message: str):
    cfg = get_alembic_config()
    command.merge(cfg, revision, message=message)


async def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "current":
        await cmd_current()
    elif cmd == "history":
        await cmd_history()
    elif cmd == "pending":
        await cmd_pending()
    elif cmd == "upgrade":
        revision = sys.argv[2] if len(sys.argv) > 2 else "head"
        await cmd_upgrade(revision)
    elif cmd == "downgrade":
        if len(sys.argv) < 3:
            print("Usage: python scripts/run_migrations.py downgrade <revision>")
            sys.exit(1)
        await cmd_downgrade(sys.argv[2])
    elif cmd == "stamp":
        if len(sys.argv) < 3:
            print("Usage: python scripts/run_migrations.py stamp <revision>")
            sys.exit(1)
        await cmd_stamp(sys.argv[2])
    elif cmd == "revision":
        message = None
        autogenerate = False
        extra_args = []
        i = 2
        while i < len(sys.argv):
            arg = sys.argv[i]
            if arg == "--autogenerate":
                autogenerate = True
            elif arg == "-m":
                i += 1
                message = sys.argv[i]
            else:
                extra_args.append(arg)
            i += 1
        cmd_revision(message or "auto-generated", autogenerate=autogenerate)
        for arg in extra_args:
            print(f"  (Note: unrecognized argument: {arg})")
    elif cmd == "merge":
        if len(sys.argv) < 3:
            print("Usage: python scripts/run_migrations.py merge <revision> <message>")
            sys.exit(1)
        cmd_merge(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "merge")
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
