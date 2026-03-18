
import pytest
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch, AsyncMock

from app.services.paper_trading_service import PaperTradingService
from app.models.trading import TradeSide, OrderType, OrderStatus
from app.models.db_models import PaperAccount, PaperPosition, PaperTrade

@pytest.mark.asyncio
async def test_paper_vs_replay_consistency():
    """
    Test that PAPER mode and HISTORICAL_REPLAY mode produce identical results 
    when given the same inputs (price, quantity, side).
    """
    # 1. Setup service
    service = PaperTradingService()
    
    # 2. Mock database and other services
    mock_db = AsyncMock()
    mock_session = AsyncMock()
    mock_db.__aenter__.return_value = mock_session
    
    # Mock account balance
    mock_account = PaperAccount(id=1, total_usdt=Decimal("100000.0"))
    mock_session.execute.side_effect = [
        MagicMock(scalar_one_or_none=lambda: mock_account), # get_balance
        MagicMock(scalar_one_or_none=lambda: None),         # get_position
        MagicMock(scalar_one_or_none=lambda: mock_account), # _get_usdt_balance in create_order
        MagicMock(scalar_one_or_none=lambda: None),         # idempotency check
        MagicMock(scalar_one_or_none=lambda: mock_account), # get_balance in create_order
        MagicMock(scalars=lambda: MagicMock(all=lambda: [])), # get_positions in create_order
        MagicMock(scalar_one_or_none=lambda: mock_account), # _update_usdt_balance
        MagicMock(scalar_one_or_none=lambda: None),         # _get_position in _apply_fill
    ]
    
    # Mock risk manager to always allow
    with patch("app.services.paper_trading_service.risk_manager") as mock_risk:
        mock_risk.check_order = AsyncMock(return_value=MagicMock(allowed=True))
        mock_risk.calculate_liquidation_price.return_value = 40000.0
        
        # Mock redis and database context managers
        with patch("app.services.paper_trading_service.get_db") as mock_get_db, \
             patch("app.services.paper_trading_service.redis_get", return_value=None), \
             patch("app.services.paper_trading_service.redis_set"), \
             patch("app.services.paper_trading_service.redis_delete"):
            
            mock_get_db.return_value = mock_db
            
            symbol = "BTCUSDT"
            side = "BUY"
            quantity = 0.1
            price = 50000.0
            
            # --- PAPER MODE ---
            # Paper mode uses real time
            res_paper = await service.create_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=price,
                order_type="MARKET",
                mode="paper"
            )
            
            # --- HISTORICAL REPLAY MODE ---
            # Replay mode uses simulated time
            sim_time = datetime(2026, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
            service.set_simulated_time(sim_time)
            
            # Reset mocks for second call
            mock_session.execute.side_effect = [
                MagicMock(scalar_one_or_none=lambda: mock_account), # get_balance
                MagicMock(scalar_one_or_none=lambda: None),         # get_position
                MagicMock(scalar_one_or_none=lambda: mock_account), # _get_usdt_balance in create_order
                MagicMock(scalar_one_or_none=lambda: None),         # idempotency check
                MagicMock(scalar_one_or_none=lambda: mock_account), # get_balance in create_order
                MagicMock(scalars=lambda: MagicMock(all=lambda: [])), # get_positions in create_order
                MagicMock(scalar_one_or_none=lambda: mock_account), # _update_usdt_balance
                MagicMock(scalar_one_or_none=lambda: None),         # _get_position in _apply_fill
            ]
            
            res_replay = await service.create_order(
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=price,
                order_type="MARKET",
                mode="historical_replay",
                session_id="TEST_SESSION_001"
            )
            
            # --- VERIFICATION ---
            # Compare prices, quantities, fees, etc.
            # (Tolerance < 0.01 for price and quantity as per SPEC)
            
            print(f"Paper Price: {res_paper['price']}, Replay Price: {res_replay['price']}")
            print(f"Paper Fee: {res_paper['fee']}, Replay Fee: {res_replay['fee']}")
            
            assert abs(res_paper["price"] - res_replay["price"]) < 0.01
            assert abs(res_paper["quantity"] - res_replay["quantity"]) < 0.00000001
            assert abs(res_paper["fee"] - res_replay["fee"]) < 0.01
            assert res_paper["status"] == res_replay["status"]
            assert res_paper["side"] == res_replay["side"]
            
            # Verify timestamps: paper should be now, replay should be sim_time
            replay_time = datetime.fromisoformat(res_replay["created_at"])
            assert replay_time == sim_time
            
            print("Consistency check PASSED!")

if __name__ == "__main__":
    asyncio.run(test_paper_vs_replay_consistency())
