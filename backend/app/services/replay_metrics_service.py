"""
ReplayMetricsService
Computes performance metrics for historical replay sessions and suggests matching backtests.
"""

import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

from sqlalchemy import select, update

from app.services.database import get_db
from app.services.performance_service import performance_service
from app.models.db_models import ReplaySession, BacktestResult, EquitySnapshot, PaperTrade

logger = logging.getLogger(__name__)


def compute_params_hash(params: dict) -> str:
    """Compute SHA256 hash of strategy parameters for matching."""
    import hashlib
    import json
    if not params:
        params = {}
    return hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()


class ReplayMetricsService:

    async def compute_and_store_metrics(self, session_id: str) -> Dict[str, Any]:
        """
        Compute complete performance metrics for a replay session and store in DB.
        Returns the computed metrics dict.
        
        IMPORTANT: This method always queries data filtered by session_id to ensure
        metrics are computed from the correct session's trades only.
        """
        async with get_db() as session:
            # 1. Get session info
            stmt = select(ReplaySession).where(ReplaySession.replay_session_id == session_id)
            result = await session.execute(stmt)
            replay_session = result.scalar_one_or_none()

            if not replay_session:
                logger.error(f"Replay session {session_id} not found")
                return {}

            start_time = replay_session.start_time or datetime(2024, 1, 1)
            end_time = replay_session.end_time or datetime.now()
            initial_capital = float(replay_session.initial_capital) if replay_session.initial_capital else 100000.0

            # 2. Count actual trades for this session before computing metrics (for validation)
            from sqlalchemy import func as sqlfunc
            trade_count_stmt = (
                select(sqlfunc.count(PaperTrade.id))
                .where(PaperTrade.session_id == session_id)
            )
            actual_trade_count_result = await session.execute(trade_count_stmt)
            actual_trade_count = actual_trade_count_result.scalar() or 0
            logger.info(f"[Replay Metrics] Session {session_id}: found {actual_trade_count} raw trades in paper_trades table")

            # 3. Compute metrics using PerformanceService with session_id filter
            # This ensures only trades belonging to this session are included
            metrics = await performance_service.calculate_metrics(
                start_date=start_time,
                end_date=end_time,
                initial_capital=initial_capital,
                session_id=session_id,
            )

            # 4. Validate: computed total_trades should be reasonable
            computed_total_trades = metrics.get("total_trades", 0)
            
            # Log validation info for debugging
            logger.info(
                f"[Replay Metrics] Session {session_id}: computed_total_trades={computed_total_trades}, "
                f"actual_raw_trades={actual_trade_count}"
            )
            
            # Note: total_trades counts CLOSED trade pairs, while actual_trade_count is raw trades
            # They won't match exactly, but we check for obvious inconsistencies
            # If computed_total_trades seems unreasonably high compared to raw trades, log a warning
            if computed_total_trades > 0 and actual_trade_count > 0:
                # Each closed pair needs at least 2 trades (entry + exit), so total_trades <= raw_trades / 2
                max_expected_trades = actual_trade_count // 2 + 1  # +1 for margin
                if computed_total_trades > max_expected_trades:
                    logger.warning(
                        f"[Replay Metrics] VALIDATION WARNING for session {session_id}: "
                        f"computed_total_trades ({computed_total_trades}) exceeds expected max ({max_expected_trades}) "
                        f"based on raw trade count ({actual_trade_count}). "
                        f"This may indicate session_id filtering is not working correctly."
                    )
            elif computed_total_trades > 0 and actual_trade_count == 0:
                logger.warning(
                    f"[Replay Metrics] VALIDATION WARNING for session {session_id}: "
                    f"computed_total_trades ({computed_total_trades}) > 0 but no raw trades found. "
                    f"This indicates possible data contamination from other sessions."
                )

            # 5. Add session_id to metrics for traceability
            metrics["replay_session_id"] = session_id
            metrics["computed_at"] = datetime.now().isoformat()
            metrics["data_source"] = "REALTIME_COMPUTED"

            # 6. Compute params_hash
            params_hash = compute_params_hash(replay_session.params or {})

            # 7. Store in DB (update the session's metrics field)
            await session.execute(
                update(ReplaySession)
                .where(ReplaySession.replay_session_id == session_id)
                .values(
                    metrics=metrics,
                    params_hash=params_hash,
                )
            )
            await session.commit()

            logger.info(
                f"[Replay Metrics] Stored metrics for session {session_id}: "
                f"total_return={metrics.get('total_return', 'N/A')}, "
                f"total_trades={computed_total_trades}, "
                f"win_rate={metrics.get('win_rate', 'N/A')}"
            )
            return metrics

    async def suggest_backtest_matches(
        self, session_id: str, limit: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Suggest matching BacktestResult records for a replay session.
        Priority: exact params_hash match > strategy_type+symbol fuzzy match.
        """
        async with get_db() as session:
            # 1. Get replay session
            stmt = select(ReplaySession).where(ReplaySession.replay_session_id == session_id)
            result = await session.execute(stmt)
            replay = result.scalar_one_or_none()

            if not replay:
                return []

            matches = []
            seen_ids = set()

            # 2. Exact params_hash match first
            if replay.params_hash:
                stmt = select(BacktestResult).where(BacktestResult.params_hash == replay.params_hash)
                result = await session.execute(stmt)
                exact_matches = result.scalars().all()
                for bt in exact_matches:
                    if bt.id not in seen_ids:
                        seen_ids.add(bt.id)
                        matches.append({
                            "id": bt.id,
                            "strategy_type": bt.strategy_type,
                            "symbol": bt.symbol,
                            "interval": bt.interval,
                            "params": bt.params or {},
                            "params_hash": bt.params_hash,
                            "metrics": bt.metrics or {},
                            "match_type": "params_hash",
                            "created_at": bt.created_at.isoformat() if bt.created_at else None,
                        })

            # 3. Fuzzy match: same strategy_type + symbol
            filter_conditions = []
            if replay.strategy_type:
                filter_conditions.append(BacktestResult.strategy_type == replay.strategy_type)
            if replay.symbol:
                filter_conditions.append(BacktestResult.symbol == replay.symbol.upper())

            if filter_conditions and len(matches) < limit:
                stmt = (
                    select(BacktestResult)
                    .where(*filter_conditions)
                    .order_by(BacktestResult.created_at.desc())
                    .limit(limit)
                )
                result = await session.execute(stmt)
                fuzzy_matches = result.scalars().all()
                for bt in fuzzy_matches:
                    if bt.id not in seen_ids and len(matches) < limit:
                        seen_ids.add(bt.id)
                        matches.append({
                            "id": bt.id,
                            "strategy_type": bt.strategy_type,
                            "symbol": bt.symbol,
                            "interval": bt.interval,
                            "params": bt.params or {},
                            "params_hash": bt.params_hash,
                            "metrics": bt.metrics or {},
                            "match_type": "strategy_symbol",
                            "created_at": bt.created_at.isoformat() if bt.created_at else None,
                        })

            return matches

    async def align_equity_curves(
        self, replay_session_id: str, backtest_id: int
    ) -> Dict[str, Any]:
        """
        Align replay equity curve (from EquitySnapshot) with backtest equity curve.
        Normalizes both to relative performance (starting at 100).
        """
        async with get_db() as session:
            # 1. Get replay equity from EquitySnapshot
            stmt = (
                select(EquitySnapshot)
                .where(EquitySnapshot.session_id == replay_session_id)
                .order_by(EquitySnapshot.timestamp.asc())
            )
            result = await session.execute(stmt)
            replay_snapshots = result.scalars().all()

            replay_equity = []
            replay_start = None
            for s in replay_snapshots:
                if replay_start is None and s.total_equity:
                    replay_start = float(s.total_equity)
                replay_equity.append({
                    "timestamp": s.timestamp.isoformat() if s.timestamp else None,
                    "equity": float(s.total_equity) if s.total_equity else 0,
                })

            # 2. Get backtest equity from BacktestResult
            stmt = select(BacktestResult).where(BacktestResult.id == backtest_id)
            result = await session.execute(stmt)
            backtest = result.scalar_one_or_none()

            backtest_equity = []
            backtest_start = None
            if backtest and backtest.equity_curve:
                for point in backtest.equity_curve:
                    equity_val = float(point.get("v", point.get("equity", 0)))
                    if backtest_start is None and equity_val:
                        backtest_start = equity_val
                    backtest_equity.append({
                        "timestamp": point.get("t") or point.get("timestamp") or point.get("time"),
                        "equity": equity_val,
                    })

            # 3. Normalize both to relative (starting at 100)
            normalized_replay = []
            for i, p in enumerate(replay_equity):
                if replay_start and replay_start > 0:
                    rel = (p["equity"] / replay_start) * 100
                else:
                    rel = 100
                normalized_replay.append({
                    "timestamp": p["timestamp"],
                    "relative_equity": round(rel, 4),
                })

            normalized_backtest = []
            for i, p in enumerate(backtest_equity):
                if backtest_start and backtest_start > 0:
                    rel = (p["equity"] / backtest_start) * 100
                else:
                    rel = 100
                normalized_backtest.append({
                    "timestamp": p["timestamp"],
                    "relative_equity": round(rel, 4),
                })

            return {
                "replay_session_id": replay_session_id,
                "backtest_id": backtest_id,
                "replay_equity": replay_equity,
                "backtest_equity": backtest_equity,
                "normalized_replay": normalized_replay,
                "normalized_backtest": normalized_backtest,
                "replay_start_value": replay_start,
                "backtest_start_value": backtest_start,
                "aligned": len(normalized_replay) > 0 and len(normalized_backtest) > 0,
            }


# Singleton
replay_metrics_service = ReplayMetricsService()
