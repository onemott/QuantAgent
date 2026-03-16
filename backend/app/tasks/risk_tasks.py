
import logging
from sqlalchemy import select
from app.services.database import get_db

logger = logging.getLogger(__name__)

async def short_squeeze_monitor_task():
    """
    Monitor short positions for short squeeze conditions.
    If triggered, log alert (auto-close not implemented in this task loop yet).
    """
    try:
        from app.models.db_models import PaperPosition
        from app.services.binance_service import binance_service
        from app.services.risk_manager import risk_manager

        async with get_db() as session:
            # Get all short positions
            stmt = select(PaperPosition).where(PaperPosition.quantity < 0)
            result = await session.execute(stmt)
            shorts = result.scalars().all()

            if not shorts:
                return

            for pos in shorts:
                try:
                    current_price = await binance_service.get_price(pos.symbol)
                    if current_price > 0:
                        squeeze = await risk_manager.check_short_squeeze(
                            pos.symbol, 
                            current_price, 
                            float(pos.avg_price), 
                            float(pos.quantity)
                        )
                        if squeeze:
                            logger.info(f"Monitor: Short Squeeze detected for {pos.symbol}! Triggering FORCE CLOSE.")
                            from app.services.paper_trading_service import paper_trading_service
                            
                            # Force close the short position
                            # Since close_all_positions takes a dict of prices, we construct one
                            current_prices = {pos.symbol: current_price}
                            try:
                                # We only want to close THIS specific position, but close_all_positions iterates all.
                                # Better to use create_order directly to close the short.
                                # Short -> Buy to close.
                                await paper_trading_service.create_order(
                                    symbol=pos.symbol,
                                    side="BUY",
                                    quantity=abs(float(pos.quantity)),
                                    price=current_price,
                                    order_type="MARKET"
                                )
                                logger.warning(f"FORCE CLOSE executed for {pos.symbol} due to Short Squeeze.")
                            except Exception as close_err:
                                logger.error(f"Failed to force close {pos.symbol}: {close_err}")

                except Exception as e:
                    logger.warning(f"Error monitoring short {pos.symbol}: {e}")
                    
    except Exception as e:
        logger.error(f"Error in short squeeze monitor: {e}")
