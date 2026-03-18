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
from sqlalchemy import update

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
        self._db_update_interval_sec = 30 # Update DB every 30 seconds
        self._start_real_time = 0
        self._start_sim_time: Optional[datetime] = None

    def _ensure_tz_aware(self, dt: datetime) -> datetime:
        """Ensure datetime is timezone-aware (UTC)."""
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    def get_current_simulated_time(self) -> datetime:
        """Calculate the current simulated time based on the clock and speed."""
        if not self.is_running or not self.data or self.cursor >= len(self.data):
            # If not running or at the end, return the last known time or the current cursor's time
            if self.cursor < len(self.data):
                return self._ensure_tz_aware(self.data[self.cursor].datetime)
            return self._ensure_tz_aware(self.data[-1].datetime) if self.data else self.config.start_time

        if self.is_paused:
            # If paused, return the time of the current bar
            return self._ensure_tz_aware(self.data[self.cursor].datetime)

        # Calculate how much real time has passed since we started (or resumed)
        start_sim = self._ensure_tz_aware(self._start_sim_time)
        current_bar_dt = self._ensure_tz_aware(self.data[self.cursor].datetime)
        sim_elapsed_at_cursor = (current_bar_dt - start_sim).total_seconds()
        real_now_elapsed = time.time() - self._start_real_time
        
        # simulated_now = start_sim_time + real_now_elapsed * speed
        # But we must ensure it doesn't exceed the next bar's time if we are waiting for it
        # Actually, it's better to just let it run smoothly.
        sim_now_total_seconds = real_now_elapsed * self.config.speed
        current_sim_time = start_sim + timedelta(seconds=sim_now_total_seconds)
        
        # Ensure config times are timezone-aware for comparison
        config_start = self._ensure_tz_aware(self.config.start_time)
        config_end = self._ensure_tz_aware(self.config.end_time)
        
        # Clamp it between start and end
        if current_sim_time < config_start:
            return config_start
        if current_sim_time > config_end:
            return config_end
            
        return current_sim_time

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
        except Exception as e:
            logger.error(f"Failed to update DB progress for {session_id}: {e}")

    async def _load_and_sort_data(self, symbol: str, interval: str):
        """Load data from ClickHouse and sort by timestamp"""
        logger.info(f"Loading historical data for {symbol} {interval} from {self.config.start_time} to {self.config.end_time}")
        
        # ClickHouseService.query_klines already returns data sorted by open_time ASC
        rows = await clickhouse_service.query_klines(
            symbol=symbol,
            interval=interval,
            start=self.config.start_time,
            end=self.config.end_time,
            limit=1000000 # Large limit for replay
        )
        
        self.data = [
            BarData(
                symbol=symbol,
                datetime=r["open_time"],
                open=r["open"],
                high=r["high"],
                low=r["low"],
                close=r["close"],
                volume=r["volume"],
                interval=interval
            )
            for r in rows
        ]
        self.cursor = 0
        logger.info(f"Loaded {len(self.data)} bars for replay")

    async def subscribe(self, symbols: List[str], interval: str, callback: Callable):
        """
        Implementation of DataAdapter.subscribe.
        For Historical Replay, we use this to register the callback with the bus.
        """
        for symbol in symbols:
            # For simplicity, we assume one symbol per replay session for now
            await self._load_and_sort_data(symbol, interval)
            # Register callback with bus
            self.bus.subscribe_bars(callback)

    async def get_history(self, symbol: str, interval: str, start: datetime, end: datetime) -> List[BarData]:
        """Fetch historical data directly"""
        return await clickhouse_service.query_klines(symbol, interval, start, end)

    async def start_playback(self):
        """Start the replay loop with accurate timing"""
        if not self.data:
            logger.warning("No data loaded for replay. Call subscribe first.")
            return

        self.is_running = True
        self.is_paused = False
        
        self._start_real_time = time.time()
        self._start_sim_time = self.data[self.cursor].datetime
        
        logger.info(f"Replay playback started at {self._start_sim_time} with speed {self.config.speed}x")
        
        # Initial DB update
        await self._update_db_progress()
        
        while self.is_running and self.cursor < len(self.data):
            if self.is_paused:
                # When paused, we need to reset the start_real_time when we resume
                await asyncio.sleep(0.1)
                self._reset_timing_reference()
                continue

            current_bar = self.data[self.cursor]
            
            # Publish bar to bus
            await self.bus.publish_bar(current_bar)
            
            self.cursor += 1

            # Periodically update DB with current progress
            if (datetime.now() - self._last_db_update_time).total_seconds() > self._db_update_interval_sec:
                await self._update_db_progress()

            if self.cursor < len(self.data):
                next_bar = self.data[self.cursor]
                
                # Accurate sleep: Calculate how much real time should have passed since start
                sim_elapsed = (next_bar.datetime - self._start_sim_time).total_seconds()
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
        logger.info("Historical replay completed")

    def _reset_timing_reference(self):
        """Reset the real-time vs sim-time reference after a pause or jump"""
        if self.cursor < len(self.data) and self._start_sim_time:
            self._start_real_time = time.time() - (self.data[self.cursor].datetime - self._start_sim_time).total_seconds() / self.config.speed

    def stop_playback(self):
        """Stop the replay loop"""
        self.is_running = False
        self.is_paused = False
        logger.info("Replay stopped")

    def pause_playback(self):
        """Pause the replay"""
        self.is_paused = True
        logger.info(f"Replay paused at cursor {self.cursor}, time: {self.data[self.cursor].datetime if self.cursor < len(self.data) else 'N/A'}")

    def resume_playback(self):
        """Resume the replay"""
        self.is_paused = False
        logger.info("Replay resumed")

    def set_start_timestamp(self, timestamp: datetime):
        """Reset the data cursor to the target timestamp"""
        # Normalize timestamp to UTC for consistent comparison
        from datetime import timezone
        if timestamp.tzinfo is None:
            # Naive datetime - assume UTC
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        else:
            timestamp = timestamp.astimezone(timezone.utc)
        
        # Find the index of the first bar with datetime >= timestamp
        for i, bar in enumerate(self.data):
            bar_time = bar.datetime
            # Normalize bar datetime too
            if bar_time.tzinfo is None:
                bar_time = bar_time.replace(tzinfo=timezone.utc)
            else:
                bar_time = bar_time.astimezone(timezone.utc)
                
            if bar_time >= timestamp:
                self.cursor = i
                logger.info(f"Replay cursor reset to {i}, time: {bar.datetime}")
                # Reset timing if we are running (not paused)
                if self.is_running and not self.is_paused:
                    self._reset_timing_reference()
                return
        
        # If not found, set to end
        self.cursor = len(self.data)
        logger.warning(f"Timestamp {timestamp} not found in loaded data. Cursor set to end.")

    async def get_valid_date_range(self, symbol: str) -> Dict[str, Any]:
        """Query ClickHouse for valid date range of a symbol"""
        return await clickhouse_service.get_valid_date_range(symbol)
