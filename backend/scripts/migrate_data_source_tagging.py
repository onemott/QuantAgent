"""
Migration script: Add data_source tagging and params_hash to existing records.
Run once after applying the 09_analytics_data_tagging.sql migration.

Usage: python scripts/migrate_data_source_tagging.py
"""
import asyncio
import hashlib
import json
from app.services.database import get_db


def compute_params_hash(params: dict) -> str:
    if not params:
        params = {}
    return hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()


async def migrate():
    print("Starting data source tagging migration...")

    async with get_db() as session:
        from sqlalchemy import select
        from app.models.db_models import BacktestResult, PaperTrade, EquitySnapshot, ReplaySession

        # 1. Tag all existing BacktestResult records
        result = await session.execute(select(BacktestResult))
        backtests = result.scalars().all()
        for bt in backtests:
            bt.data_source = 'BACKTEST'
            bt.params_hash = compute_params_hash(bt.params or {})
        print(f"Tagged {len(backtests)} backtest results")

        # 2. Tag all existing PaperTrade records
        result = await session.execute(select(PaperTrade))
        trades = result.scalars().all()
        for t in trades:
            t.data_source = 'PAPER'
        print(f"Tagged {len(trades)} paper trades")

        # 3. Tag all existing EquitySnapshot records
        result = await session.execute(select(EquitySnapshot))
        snapshots = result.scalars().all()
        for s in snapshots:
            s.data_source = 'PAPER'
        print(f"Tagged {len(snapshots)} equity snapshots")

        # 4. Tag all existing ReplaySession records
        result = await session.execute(select(ReplaySession))
        sessions = result.scalars().all()
        for s in sessions:
            s.data_source = 'REPLAY'
            s.params_hash = compute_params_hash(s.params or {})
            s.metrics = s.metrics or {}
        print(f"Tagged {len(sessions)} replay sessions")

        # 5. Try to auto-link ReplaySessions to BacktestResults by params_hash
        # Build params_hash -> backtest_id map
        result = await session.execute(select(BacktestResult.id, BacktestResult.params_hash))
        bt_hash_map = {row.params_hash: row.id for row in result.all() if row.params_hash}

        result = await session.execute(select(ReplaySession))
        sessions = result.scalars().all()
        linked = 0
        for s in sessions:
            if s.params_hash and s.params_hash in bt_hash_map:
                s.backtest_id = bt_hash_map[s.params_hash]
                linked += 1
        print(f"Auto-linked {linked} replay sessions to backtest results")

        await session.commit()
        print("Migration complete!")


if __name__ == "__main__":
    asyncio.run(migrate())
