"""
Task Scheduler Service
Manages periodic background tasks using APScheduler.
"""

import logging
from datetime import datetime, timedelta, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.redis import RedisJobStore
from apscheduler.executors.pool import ThreadPoolExecutor
from app.core.config import settings
from app.services.database import get_db
from app.models.db_models import AgentMemory
from app.services.binance_service import binance_service
from sqlalchemy import select
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ── Standalone Task Functions (Picklable) ─────────────────────────────────────

async def health_log_task():
    logger.info("Scheduler is alive. System check passed.")

async def daily_report_task():
    """Generate daily TCA report."""
    try:
        from app.services.tca_service import tca_service
        report = await tca_service.generate_report()
        logger.info(f"Daily TCA Report: {report}")
        # In a real system, you might email this or save to a DailyReport table
    except Exception as e:
        logger.error(f"Failed to generate daily report: {e}")

async def match_orders_task():
    """Periodically match pending orders."""
    try:
        from app.services.paper_trading_service import paper_trading_service
        await paper_trading_service.match_orders()
    except Exception as e:
        logger.error(f"Error in order matching task: {e}")

async def equity_snapshot_task():
    """Record equity snapshot hourly."""
    try:
        from app.tasks.equity_tasks import record_equity_snapshot
        await record_equity_snapshot()
    except Exception as e:
        logger.error(f"Error in equity snapshot task: {e}")

async def auto_strategy_task():
    """Execute automated strategies."""
    try:
        from app.services.strategy_runner_service import strategy_runner_service
        await strategy_runner_service.run_all_strategies()
    except Exception as e:
        logger.error(f"Error in auto strategy task: {e}")

async def risk_monitor_task():
    """Run periodic risk checks."""
    try:
        from app.tasks.risk_tasks import short_squeeze_monitor_task
        await short_squeeze_monitor_task()
    except Exception as e:
        logger.error(f"Failed to run risk monitor task: {e}")

async def calculate_agent_pnl_task():
    """
    Backtrack Agent decisions and calculate PnL after N hours.
    Fills 'outcome_pnl' in AgentMemory.
    """
    logger.info("Starting Agent PnL Backtracking...")
    
    # Define PnL horizon (e.g., 24 hours after decision)
    HORIZON_HOURS = 24
    horizon_time = datetime.now(timezone.utc) - timedelta(hours=HORIZON_HOURS)
    
    try:
        async with get_db() as session:
            # Find memories older than horizon with null PnL
            stmt = (
                select(AgentMemory)
                .where(AgentMemory.outcome_pnl.is_(None))
                .where(AgentMemory.created_at <= horizon_time)
                .where(AgentMemory.entry_price.isnot(None))
                .where(AgentMemory.signal.in_(['BUY', 'SELL', 'LONG_REVERSAL', 'SHORT_REVERSAL']))
                .limit(100) # Process in batches
            )
            result = await session.execute(stmt)
            memories = result.scalars().all()
            
            if not memories:
                logger.info("No pending AgentMemory records for PnL calculation.")
                return

            logger.info(f"Processing {len(memories)} AgentMemory records for PnL...")
            
            for mem in memories:
                # Get current price (or price at horizon time ideally, but current is approx okay for now)
                # Ideally we should fetch historical kline at created_at + 24h
                # For simplicity, we use current price if it's roughly recent, 
                # but strictly we should use the price at T+24h.
                
                # Let's try to get the close price of the kline at created_at + 24h
                target_time = mem.created_at + timedelta(hours=HORIZON_HOURS)
                # Convert to timestamp ms
                ts = int(target_time.timestamp() * 1000)
                
                try:
                    # Fetch single kline at that time
                    klines = await binance_service.get_klines(
                        symbol=mem.symbol,
                        interval="1m",
                        limit=1,
                        start_time=ts,
                        end_time=ts + 60000
                    )
                    
                    if klines:
                        exit_price = klines[0].close
                        entry_price = float(mem.entry_price)
                        
                        pnl = 0.0
                        if mem.signal in ['BUY', 'LONG_REVERSAL']:
                            pnl = (exit_price - entry_price) / entry_price * 100
                        elif mem.signal in ['SELL', 'SHORT_REVERSAL']:
                            pnl = (entry_price - exit_price) / entry_price * 100
                            
                        mem.outcome_pnl = round(pnl, 2)
                        logger.info(f"Updated PnL for {mem.id} ({mem.symbol}): {pnl:.2f}%")
                        
                except Exception as e:
                    logger.warning(f"Failed to fetch price for memory {mem.id}: {e}")
                    continue
            
            await session.commit()
            
    except Exception as e:
        logger.error(f"Error in PnL backtracking: {e}")


# 多周期历史数据补充任务
async def backfill_multi_interval_task():
    """
    定期补充高周期历史数据 (5m, 15m, 1h, 4h, 1d)
    每小时运行一次，补充过去1小时的数据
    """
    INTERVALS = ["5m", "15m", "1h", "4h", "1d"]
    LOOKBACK_MINUTES = {
        "5m": 60,
        "15m": 120,
        "1h": 120,
        "4h": 300,
        "1d": 1440,
    }
    
    logger.info("Starting multi-interval historical data backfill...")
    
    for symbol in settings.SYMBOLS:
        for interval in INTERVALS:
            try:
                lookback = LOOKBACK_MINUTES.get(interval, 60)
                since = int((datetime.now(timezone.utc) - timedelta(minutes=lookback)).timestamp() * 1000)
                
                klines = await binance_service.get_klines(
                    symbol=symbol,
                    timeframe=interval,
                    limit=1000,
                    since=since
                )
                
                if klines:
                    logger.info(f"Backfilled {len(klines)} bars for {symbol}/{interval}")
            except Exception as e:
                logger.warning(f"Failed to backfill {symbol}/{interval}: {e}")
    
    logger.info("Multi-interval backfill completed.")


# ── Scheduler Service ─────────────────────────────────────────────────────────

class SchedulerService:
    def __init__(self):
        # Configure JobStores
        # Parse Redis URL using urllib
        parsed = urlparse(settings.REDIS_URL)
        host = parsed.hostname or 'localhost'
        port = parsed.port or 6379
        db = 0
        if parsed.path and parsed.path.startswith('/'):
            try:
                db = int(parsed.path[1:])
            except ValueError:
                pass
        password = parsed.password

        self.jobstores = {
            'default': RedisJobStore(
                jobs_key='apscheduler.jobs',
                run_times_key='apscheduler.run_times',
                host=host,
                port=port,
                db=db,
                password=password
            )
        }
        
        # self.executors = {
        #    'default': ThreadPoolExecutor(10)
        # }
        
        self.job_defaults = {
            'coalesce': False,
            'max_instances': 1
        }
        
        self.scheduler = AsyncIOScheduler(
            jobstores=self.jobstores,
            # executors=self.executors,
            job_defaults=self.job_defaults,
            timezone="UTC"
        )

    def start(self):
        """Start the scheduler."""
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("Scheduler started.")
            
            # Add default jobs here
            self.add_system_jobs()

    def stop(self):
        """Shutdown the scheduler."""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("Scheduler stopped.")

    def add_system_jobs(self):
        """Add system-level periodic tasks."""
        # Daily Report at 00:00 UTC
        self.scheduler.add_job(
            daily_report_task, 
            'cron', 
            hour=0, 
            minute=0, 
            id='daily_report', 
            replace_existing=True
        )
        
        # Example: Health Check Log every 5 mins
        self.scheduler.add_job(
            health_log_task,
            'interval',
            minutes=5,
            id='health_log',
            replace_existing=True
        )

        # Agent PnL Backtracking Task (Every 1 hour)
        self.scheduler.add_job(
            calculate_agent_pnl_task,
            'interval',
            hours=1,
            id='agent_pnl_backtrack',
            replace_existing=True
        )
        
        # Risk Monitor Task (Every 1 minute)
        self.scheduler.add_job(
            risk_monitor_task,
            'interval',
            minutes=1,
            id='risk_monitor',
            replace_existing=True
        )

        # Order Matching Task (Every 2 seconds)
        self.scheduler.add_job(
            match_orders_task,
            'interval',
            seconds=2,
            id='order_matching',
            replace_existing=True,
            max_instances=1
        )

        # Equity Snapshot Task (Every 1 hour)
        self.scheduler.add_job(
            equity_snapshot_task,
            'interval',
            hours=1,
            id='equity_snapshot',
            replace_existing=True,
            max_instances=1
        )

        # Auto Strategy Execution (Every 5 minutes)
        self.scheduler.add_job(
            auto_strategy_task,
            'interval',
            minutes=5,
            id='auto_strategy',
            replace_existing=True,
            max_instances=1
        )

        # Multi-Interval Historical Data Backfill (Every 1 hour)
        self.scheduler.add_job(
            backfill_multi_interval_task,
            'interval',
            hours=1,
            id='multi_interval_backfill',
            replace_existing=True,
            max_instances=1
        )

# Singleton
scheduler_service = SchedulerService()
