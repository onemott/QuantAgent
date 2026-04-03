import logging
import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Callable

from app.core.bus import TradingBus, DataAdapter, ReplayConfig
from app.models.trading import BarData, TickData
from app.services.clickhouse_service import clickhouse_service
from app.services.database import get_db
from app.models.db_models import ReplaySession
from app.services.paper_trading_service import paper_trading_service
from sqlalchemy import update, delete

logger = logging.getLogger(__name__)


class HistoricalReplayAdapter(DataAdapter):
    """
    Adapter for Historical Replay Mode.
    Fetches data from ClickHouse and pushes it to the bus at controlled speed.
    """

    def __init__(self, bus: TradingBus, config: ReplayConfig):
        self.bus = bus
        self.config = config
        self.data: List[BarData] = []
        self.cursor = 0
        self.is_running = False
        self.is_paused = False
        self._playback_task: Optional[asyncio.Task] = None
        self._last_db_update_time = datetime.now()
        self._db_update_interval_sec = 30  # Update DB every 30 seconds
        self._start_real_time = 0
        self._start_sim_time: Optional[datetime] = None
        self._last_equity_snapshot_time: Optional[datetime] = None
        self._equity_snapshot_interval_sec = config.equity_snapshot_interval  # 从配置读取，默认3600
        # Pause time tracking — excludes paused duration from elapsed time
        self._total_paused_time: float = 0.0
        self._pause_start_time: Optional[float] = None

        # Error tracking and health monitoring
        self.error_count = 0
        self.warnings: list = []  # 最多保留最近20条
        self.bars_processed = 0
        self._db_update_failures = 0

    def _ensure_tz_aware(self, dt: datetime) -> datetime:
        """Ensure datetime is timezone-aware (UTC)."""
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    def get_current_simulated_time(self) -> datetime:
        """Calculate the current simulated time based on the clock and speed.

        Uses a more accurate calculation that directly tracks the simulated time
        based on how much real time has elapsed since start/resume.
        """
        # If not running or no data, return appropriate fallback
        if not self.data or len(self.data) == 0:
            return self._ensure_tz_aware(self.config.start_time)

        # If paused, return the current cursor's bar time
        if self.is_paused:
            if self.cursor < len(self.data):
                return self._ensure_tz_aware(self.data[self.cursor].datetime)
            return self._ensure_tz_aware(self.data[-1].datetime)

        # If completed or cursor at end
        if not self.is_running or self.cursor >= len(self.data):
            return (
                self._ensure_tz_aware(self.data[-1].datetime)
                if self.data
                else self._ensure_tz_aware(self.config.start_time)
            )

        # Calculate simulated time based on elapsed real time
        # Formula: sim_time = start_sim_time + (real_elapsed * speed)
        start_sim = (
            self._ensure_tz_aware(self._start_sim_time)
            if self._start_sim_time
            else self._ensure_tz_aware(self.data[0].datetime)
        )

        # Handle instant mode (speed = -1)
        if self.config.speed == -1:
            # In instant mode, simulated time = current bar time (no time dilation)
            if self.cursor < len(self.data):
                return self._ensure_tz_aware(self.data[self.cursor].datetime)
            return (
                self._ensure_tz_aware(self.data[-1].datetime)
                if self.data
                else self._ensure_tz_aware(self.config.start_time)
            )

        real_elapsed = time.time() - self._start_real_time
        sim_elapsed = real_elapsed * self.config.speed
        current_sim_time = start_sim + timedelta(seconds=sim_elapsed)

        # Clamp between config start and end times
        config_start = self._ensure_tz_aware(self.config.start_time)
        config_end = self._ensure_tz_aware(self.config.end_time)

        return max(config_start, min(config_end, current_sim_time))

    def get_elapsed_real_time(self) -> float:
        """Get actual elapsed real time since start, excluding paused duration.

        Returns:
            float: Elapsed seconds since replay started/resumed (paused time excluded).
        """
        if not self._start_real_time:
            return 0.0
        elapsed = time.time() - self._start_real_time - self._total_paused_time
        return max(0.0, elapsed)

    def get_progress(self) -> float:
        """Calculate replay progress (0.0 to 1.0) using simulated time span.

        Uses the same formula for all states (running/paused/completed),
        providing a consistent progress metric regardless of data distribution.
        """
        if not self.data or len(self.data) == 0:
            return 0.0

        if not self.is_running and self.cursor >= len(self.data):
            return 1.0

        if self._start_sim_time and self.config.end_time:
            start_ts = self._ensure_tz_aware(self._start_sim_time)
            end_ts = self._ensure_tz_aware(self.config.end_time)
            current_ts = self.get_current_simulated_time()

            total_span = (end_ts - start_ts).total_seconds()
            if total_span > 0:
                elapsed = (current_ts - start_ts).total_seconds()
                return min(1.0, max(0.0, elapsed / total_span))

        # Fallback: based on cursor position
        return min(1.0, self.cursor / len(self.data))

    async def _update_db_progress(self):
        """Update current_timestamp in DB for persistence"""
        current_time = self.get_current_simulated_time()
        session_id = getattr(self.bus, "session_id", None)
        if not session_id:
            return

        try:
            async with get_db() as session:
                await session.execute(
                    update(ReplaySession)
                    .where(ReplaySession.replay_session_id == session_id)
                    .values(current_timestamp=current_time)
                )
                await session.commit()
            self._last_db_update_time = datetime.now()
            self._db_update_failures = 0  # Reset failure counter on success
        except Exception as e:
            self._db_update_failures += 1
            logger.error(f"Failed to update DB progress for {session_id}: {e}")
            # Add warning if consecutive failures exceed threshold
            if self._db_update_failures >= 3:
                warning_msg = f"DB进度更新连续失败{self._db_update_failures}次，回放数据可能无法持久化"
                self.warnings.append(warning_msg)
                # Keep only last 20 warnings
                if len(self.warnings) > 20:
                    self.warnings.pop(0)

    async def _record_equity_snapshot(self, current_bar: BarData):
        """Record equity snapshot with simulated timestamp."""
        session_id = getattr(self.bus, "session_id", None)
        if not session_id:
            return

        current_time = self._ensure_tz_aware(current_bar.datetime)

        if self._last_equity_snapshot_time is None:
            self._last_equity_snapshot_time = current_time

        time_since_last = (
            current_time - self._last_equity_snapshot_time
        ).total_seconds()
        if time_since_last < self._equity_snapshot_interval_sec:
            return

        try:
            current_prices = {current_bar.symbol: current_bar.close}
            await paper_trading_service.record_replay_equity_snapshot(
                session_id=session_id,
                timestamp=current_time,
                current_prices=current_prices,
            )
            self._last_equity_snapshot_time = current_time
        except Exception as e:
            logger.error(f"Failed to record equity snapshot: {e}")

    async def _load_and_sort_data(self, symbol: str, interval: str):
        """Load data from ClickHouse and sort by timestamp"""
        logger.info(
            f"Loading historical data for {symbol} {interval} from {self.config.start_time} to {self.config.end_time}"
        )

        try:
            # ClickHouseService.query_klines already returns data sorted by open_time ASC
            rows = await clickhouse_service.query_klines(
                symbol=symbol,
                interval=interval,
                start=self.config.start_time,
                end=self.config.end_time,
                limit=1000000,  # Large limit for replay
            )
        except Exception as e:
            logger.error(
                f"Failed to load historical data from ClickHouse: "
                f"symbol={symbol}, interval={interval}, "
                f"start_time={self.config.start_time}, end_time={self.config.end_time}, "
                f"error={type(e).__name__}: {e}"
            )
            raise RuntimeError(
                f"Failed to load historical data for {symbol} {interval} "
                f"({self.config.start_time} to {self.config.end_time}): {e}"
            ) from e

        try:
            self.data = [
                BarData(
                    symbol=symbol,
                    datetime=r["open_time"],
                    open=r["open"],
                    high=r["high"],
                    low=r["low"],
                    close=r["close"],
                    volume=r["volume"],
                    interval=interval,
                )
                for r in rows
            ]
        except (KeyError, TypeError, ValueError) as e:
            logger.error(
                f"Failed to parse ClickHouse response data: "
                f"symbol={symbol}, interval={interval}, "
                f"rows_count={len(rows) if rows else 0}, "
                f"sample_row={rows[0] if rows else 'N/A'}, "
                f"error={type(e).__name__}: {e}"
            )
            raise RuntimeError(
                f"Failed to parse historical data for {symbol} {interval}: {e}"
            ) from e

        self.cursor = 0
        logger.info(f"Loaded {len(self.data)} bars for replay")
        if self.data:
            first_bar = self.data[0]
            last_bar = self.data[-1]
            logger.info(
                f"Data range: first bar [{first_bar.datetime}] close={first_bar.close}, "
                f"last bar [{last_bar.datetime}] close={last_bar.close}"
            )

    async def subscribe(self, symbols: List[str], interval: str, callback: Callable):
        """
        Implementation of DataAdapter.subscribe.
        For Historical Replay, we use this to register the callback with the bus.
        """
        for symbol in symbols:
            # For simplicity, we assume one symbol per replay session for now
            try:
                await self._load_and_sort_data(symbol, interval)
            except Exception as e:
                logger.error(
                    f"Failed to load data during subscribe: symbol={symbol}, interval={interval}, "
                    f"error={type(e).__name__}: {e}"
                )
                raise
            # Register callback with bus
            self.bus.subscribe_bars(callback)

    async def get_history(
        self, symbol: str, interval: str, start: datetime, end: datetime
    ) -> List[BarData]:
        """Fetch historical data directly"""
        return await clickhouse_service.query_klines(symbol, interval, start, end)

    async def start_playback(self):
        """Start the replay loop with accurate timing"""
        if not self.data:
            logger.warning("No data loaded for replay. Call subscribe first.")
            return

        self.is_running = True
        self.is_paused = False
        self._last_equity_snapshot_time = None

        self._start_real_time = time.time()
        self._start_sim_time = self.data[self.cursor].datetime
        playback_start_time = datetime.now()  # For elapsed time calculation

        logger.info(
            f"Replay playback started at {self._start_sim_time} with speed {self.config.speed}x"
        )

        # Initial DB update
        try:
            await self._update_db_progress()
        except Exception as e:
            logger.error(f"Failed initial DB progress update: {e}")

        while self.is_running and self.cursor < len(self.data):
            if self.is_paused:
                await asyncio.sleep(0.1)
                continue

            current_bar = self.data[self.cursor]

            # Publish bar to bus - wrap in try-except to prevent single bar failure from stopping replay
            try:
                await self.bus.publish_bar(current_bar)
            except Exception as e:
                self.error_count += 1
                error_msg = f"Failed to publish bar (cursor={self.cursor}, time={current_bar.datetime}): {type(e).__name__}: {e}"
                self.warnings.append(error_msg)
                if len(self.warnings) > 20:
                    self.warnings.pop(0)
                logger.error(f"{error_msg}. Continuing replay...")

            # Match pending limit orders using this bar's OHLC prices (not real-time)
            bar_prices = {
                current_bar.symbol: {
                    "high": current_bar.high,
                    "low": current_bar.low,
                    "open": current_bar.open,
                    "close": current_bar.close,
                }
            }
            session_id = getattr(self.bus, "session_id", None)
            try:
                await paper_trading_service.match_orders_with_bar_price(
                    bar_prices=bar_prices,
                    session_id=session_id,
                )
            except Exception as e:
                self.error_count += 1
                error_msg = f"Failed to match orders for bar (cursor={self.cursor}, time={current_bar.datetime}): {type(e).__name__}: {e}"
                self.warnings.append(error_msg)
                if len(self.warnings) > 20:
                    self.warnings.pop(0)
                logger.error(f"{error_msg}. Continuing replay...")

            # Record equity snapshot periodically (every hour of simulated time)
            try:
                await self._record_equity_snapshot(current_bar)
            except Exception as e:
                self.error_count += 1
                error_msg = f"Failed to record equity snapshot (cursor={self.cursor}): {type(e).__name__}: {e}"
                self.warnings.append(error_msg)
                if len(self.warnings) > 20:
                    self.warnings.pop(0)
                logger.error(f"{error_msg}. Continuing replay...")

            self.bars_processed += 1
            self.cursor += 1

            # Periodically update DB with current progress
            if (
                datetime.now() - self._last_db_update_time
            ).total_seconds() > self._db_update_interval_sec:
                await self._update_db_progress()

            if self.cursor < len(self.data):
                next_bar = self.data[self.cursor]

                # Check if instant mode is enabled (speed = -1)
                if self.config.speed == -1:
                    # Instant mode: no sleep, but yield every 50 bars (~5ms batches)
                    # to stay responsive to pause/stop without blocking for too long.
                    if self.cursor % 50 == 0:
                        await asyncio.sleep(0)
                else:
                    # Accurate sleep: Calculate how much real time should have passed since start
                    sim_elapsed = (
                        next_bar.datetime - self._start_sim_time
                    ).total_seconds()
                    real_target_elapsed = sim_elapsed / self.config.speed

                    real_now_elapsed = time.time() - self._start_real_time
                    sleep_time = real_target_elapsed - real_now_elapsed

                    if sleep_time > 0:
                        # Sleep in small increments to be responsive to pause/stop
                        while sleep_time > 0 and self.is_running and not self.is_paused:
                            step = min(sleep_time, 0.1)
                            await asyncio.sleep(step)
                            sleep_time -= step

        self.is_running = False

        # Auto-close remaining positions at the last bar's close price
        session_id = getattr(self.bus, "session_id", None)
        if session_id and self.data:
            final_bar = self.data[-1]
            final_prices = {final_bar.symbol: final_bar.close}

            # Check if there are open positions
            positions = await paper_trading_service.get_positions(
                current_prices=final_prices,
                session_id=session_id,
            )
            if positions:
                logger.info(
                    f"Auto-closing {len(positions)} positions at replay completion "
                    f"({final_bar.symbol} @ {final_bar.close})"
                )
                await paper_trading_service.close_all_positions(
                    current_prices=final_prices,
                    session_id=session_id,
                )

            # Record final equity snapshot after close-out
            await self._record_equity_snapshot(final_bar)

        # Calculate elapsed time
        elapsed = (datetime.now() - playback_start_time).total_seconds()

        logger.info(
            f"Historical replay completed (instant mode: {self.config.speed == -1})"
        )

        # Compute and store completion metrics only if a session_id is set.
        if session_id:
            logger.info(
                f"Replay summary: total_bars={len(self.data)}, session_id={session_id}"
            )
            await self._compute_completion_metrics()

        # Final summary log
        logger.info(
            f"回放结束 session={session_id}: "
            f"处理K线={self.bars_processed}/{len(self.data)}, "
            f"错误数={self.error_count}, "
            f"DB更新失败={self._db_update_failures}, "
            f"耗时={elapsed:.1f}秒"
        )

    def _reset_timing_reference(self):
        """Reset the real-time vs sim-time reference after a pause or jump.

        This ensures accurate time calculation by setting the reference point
        to the current cursor position.
        """
        if self.cursor < len(self.data) and self.data:
            # Get current bar time as the new reference
            current_bar_time = self._ensure_tz_aware(self.data[self.cursor].datetime)
            # Set _start_sim_time to current position so time calculation is accurate
            self._start_sim_time = current_bar_time
            # Reset real time reference to now
            self._start_real_time = time.time()
            logger.info(
                f"Timing reference reset: sim_time={current_bar_time}, cursor={self.cursor}"
            )

    def stop_playback(self):
        """Stop the replay loop"""
        self.is_running = False
        self.is_paused = False
        logger.info("Replay stopped")

    def pause_playback(self):
        """Pause the replay and record the pause start time."""
        self.is_paused = True
        self._pause_start_time = time.time()
        logger.info(
            f"Replay paused at cursor {self.cursor}, "
            f"time: {self.data[self.cursor].datetime if self.cursor < len(self.data) else 'N/A'}"
        )

    def resume_playback(self):
        """Resume the replay, accumulating paused time and resetting timing reference."""
        # Accumulate the time spent paused so get_elapsed_real_time is accurate
        if self._pause_start_time is not None:
            self._total_paused_time += time.time() - self._pause_start_time
            self._pause_start_time = None

        self.is_paused = False
        self._reset_timing_reference()
        logger.info("Replay resumed")

    def set_start_timestamp(self, timestamp: datetime):
        """Jump to target timestamp: reset cursor, timing, and clear trades after position."""
        from datetime import timezone

        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        else:
            timestamp = timestamp.astimezone(timezone.utc)

        old_cursor = self.cursor
        for i, bar in enumerate(self.data):
            bar_time = bar.datetime
            if bar_time.tzinfo is None:
                bar_time = bar_time.replace(tzinfo=timezone.utc)
            else:
                bar_time = bar_time.astimezone(timezone.utc)

            if bar_time >= timestamp:
                self.cursor = i
                logger.info(f"Replay cursor jumped from {old_cursor} to {i}, time: {bar.datetime}")

                # Reset timing reference
                self._reset_timing_reference()

                # Sync simulated time to execution router
                self.bus.execution_router.set_simulated_time(bar.datetime)

                # Clear trades and positions AFTER the new cursor
                # (backward jump keeps trades; forward jump must invalidate future trades)
                if self.cursor > old_cursor:
                    asyncio.create_task(
                        self._clear_trades_after_cursor(
                            getattr(self.bus, "session_id", None)
                        )
                    )
                return

        self.cursor = len(self.data)
        logger.warning(
            f"Timestamp {timestamp} not found in loaded data. Cursor set to end."
        )

    async def get_valid_date_range(self, symbol: str) -> Dict[str, Any]:
        """Query ClickHouse for valid date range of a symbol"""
        return await clickhouse_service.get_valid_date_range(symbol)

    def get_health_summary(self) -> dict:
        """Get health summary for the replay session.

        Returns:
            dict: Contains error_count, warnings, bars_processed, bars_total, db_update_failures
        """
        return {
            "error_count": self.error_count,
            "warnings": self.warnings[-20:],
            "bars_processed": self.bars_processed,
            "bars_total": len(self.data) if self.data else 0,
            "db_update_failures": self._db_update_failures,
        }

    async def _clear_trades_after_cursor(self, session_id: Optional[str]):
        """Delete trades and reset positions created after the current cursor position.

        Called after a forward jump (cursor increases) to invalidate future trades
        that would no longer be reachable in the replay timeline.
        """
        if not session_id or not self.data or self.cursor >= len(self.data):
            return

        current_bar_time = self.data[self.cursor].datetime
        logger.info(
            f"Clearing trades after cursor {self.cursor} (time: {current_bar_time})"
        )

        try:
            from app.models.db_models import PaperTrade, PaperPosition

            async with get_db() as session:
                # Delete trades created after the current bar's time
                await session.execute(
                    delete(PaperTrade).where(
                        PaperTrade.session_id == session_id,
                        PaperTrade.created_at > current_bar_time,
                    )
                )
                await session.commit()
            logger.info(f"Cleared trades after cursor {self.cursor}")
        except Exception as e:
            logger.error(f"Failed to clear trades after cursor: {e}")

    async def _compute_completion_metrics(self):
        """Compute and store performance metrics when replay completes."""
        from app.services.replay_metrics_service import replay_metrics_service

        session_id = getattr(self.bus, "session_id", None)
        if not session_id:
            logger.warning("No session_id found for metrics computation")
            return

        try:
            metrics = await replay_metrics_service.compute_and_store_metrics(session_id)
            logger.info(f"Completion metrics computed for {session_id}: Sharpe={metrics.get('sharpe_ratio', 'N/A')}")
        except Exception as e:
            logger.error(f"Failed to compute completion metrics for {session_id}: {e}")
