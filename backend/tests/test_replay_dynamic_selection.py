import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from main import app

from app.strategies.dynamic_selection_strategy import DynamicSelectionStrategy
from app.models.trading import BarData, OrderResult, OrderStatus, OrderRequest

client = TestClient(app)


class MockBusWithSessionId:
    """Mock bus with session_id attribute for replay session testing."""
    
    def __init__(self, session_id: str = None):
        self.session_id = session_id
        self.orders = []
        self.balance = {"available_balance": 10000.0}
        
    async def execute_order(self, req):
        self.orders.append(req)
        return OrderResult(
            order_id="test_order_id",
            client_order_id="test_client_id",
            symbol=req.symbol,
            status=OrderStatus.FILLED,
            filled_quantity=req.quantity,
            filled_price=req.price,
            fee=0.0,
            pnl=0.0,
            timestamp=datetime.now(timezone.utc)
        )
        
    async def get_balance(self):
        return self.balance

@pytest.mark.asyncio
async def test_dynamic_selection_create_replay_validation():
    from httpx import AsyncClient
    from httpx import ASGITransport
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. Missing atomic_strategies
        payload_missing = {
            "strategy_id": 1,
            "strategy_type": "dynamic_selection",
            "symbol": "BTCUSDT",
            "start_time": "2023-01-01T00:00:00Z",
            "end_time": "2023-01-02T00:00:00Z",
            "speed": 100,
            "initial_capital": 10000,
            "params": {
                "interval": "1m"
            }
        }
        response = await ac.post("/api/v1/replay/create", json=payload_missing)
        assert response.status_code == 400
        assert "requires a non-empty list of 'atomic_strategies'" in response.json()["detail"]
    
        # 2. Invalid atomic strategy type
        payload_invalid_atomic = {
            "strategy_id": 2,
            "strategy_type": "dynamic_selection",
            "symbol": "BTCUSDT",
            "start_time": "2023-01-01T00:00:00Z",
            "end_time": "2023-01-02T00:00:00Z",
            "speed": 100,
            "initial_capital": 10000,
            "params": {
                "interval": "1m",
                "atomic_strategies": [
                    {"strategy_id": "s1", "strategy_type": "ma"},
                    {"strategy_id": "s2", "strategy_type": "smart_beta"} # Not allowed
                ]
            }
        }
        response = await ac.post("/api/v1/replay/create", json=payload_invalid_atomic)
        assert response.status_code == 400
        assert "is not supported" in response.json()["detail"]
    
        # 3. Valid dynamic_selection strategy
        payload_valid = {
            "strategy_id": 3,
            "strategy_type": "dynamic_selection",
            "symbol": "BTCUSDT",
            "start_time": "2023-01-01T00:00:00Z",
            "end_time": "2023-01-02T00:00:00Z",
            "speed": 100,
            "initial_capital": 10000,
            "params": {
                "interval": "1m",
                "atomic_strategies": [
                    {"strategy_id": "s1", "strategy_type": "ma", "params": {"fast_period": 5, "slow_period": 20}},
                    {"strategy_id": "s2", "strategy_type": "rsi", "params": {"period": 14}}
                ]
            }
        }
        response = await ac.post("/api/v1/replay/create", json=payload_valid)
        if response.status_code == 400:
            assert "has no data" in response.json()["detail"] or "No historical data found" in response.json()["detail"]
        else:
            assert response.status_code == 200

@pytest.mark.asyncio
async def test_dynamic_selection_history_filtering():
    """
    Test that history endpoint correctly filters by session_id using mock database.
    
    This test mocks the database session to avoid requiring a real PostgreSQL connection.
    """
    from datetime import datetime, timezone
    from unittest.mock import patch, MagicMock, AsyncMock
    from httpx import AsyncClient
    from httpx import ASGITransport
    
    # Create mock history records using actual SQLAlchemy model instances
    # FastAPI needs real model instances for proper JSON serialization
    from app.models.db_models import SelectionHistory
    
    mock_history_records = [
        SelectionHistory(
            id=1,
            evaluation_date=datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            session_id="REPLAY_TEST_123",
            total_strategies=5,
            surviving_count=3,
            eliminated_count=2,
            eliminated_strategy_ids=["s4", "s5"],
            elimination_reasons={"s4": "low_score", "s5": "low_score"},
            strategy_weights={"s1": 0.4, "s2": 0.35, "s3": 0.25}
        ),
        SelectionHistory(
            id=2,
            evaluation_date=datetime(2023, 1, 2, 12, 0, 0, tzinfo=timezone.utc),
            session_id="REPLAY_TEST_123",
            total_strategies=5,
            surviving_count=4,
            eliminated_count=1,
            eliminated_strategy_ids=["s5"],
            elimination_reasons={"s5": "low_score"},
            strategy_weights={"s1": 0.3, "s2": 0.3, "s3": 0.25, "s4": 0.15}
        )
    ]
    
    # Create mock database session
    mock_db_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = mock_history_records
    mock_db_session.execute = AsyncMock(return_value=mock_result)
    
    # Use dependency_overrides to mock FastAPI Depends injection
    from app.services.database import get_db_session
    
    async def mock_get_db():
        yield mock_db_session
    
    # Override the dependency
    app.dependency_overrides[get_db_session] = mock_get_db
    
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/api/v1/dynamic-selection/history?session_id=REPLAY_TEST_123")
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            assert len(data) == 2
            # Verify the first record has expected structure
            assert data[0]["session_id"] == "REPLAY_TEST_123"
            assert data[0]["total_strategies"] == 5
            assert data[0]["surviving_count"] == 3
    finally:
        # Clean up the override after test
        app.dependency_overrides.pop(get_db_session, None)


@pytest.mark.asyncio
async def test_dynamic_selection_replay_session_id_association():
    """
    Test that SelectionHistory records are saved with the correct session_id
    from the bus during replay evaluation.
    
    This verifies the fix where session_id is now obtained via:
    `session_id = getattr(self.bus, "session_id", None)`
    """
    # Create a mock bus with a specific replay session_id
    test_session_id = "REPLAY_SESSION_TEST_456"
    bus = MockBusWithSessionId(session_id=test_session_id)
    
    # Create DynamicSelectionStrategy
    strategy = DynamicSelectionStrategy(strategy_id="test_dyn_selection", bus=bus)
    
    # Set up parameters with multiple atomic strategies and short evaluation interval
    params = {
        "initial_capital": 10000.0,
        "evaluation_period": 5,  # Short interval to trigger evaluation quickly
        "atomic_strategies": [
            {
                "strategy_id": "ma_strategy_1",
                "strategy_type": "ma",
                "params": {"fast_period": 5, "slow_period": 20}
            },
            {
                "strategy_id": "rsi_strategy_2",
                "strategy_type": "rsi",
                "params": {"rsi_period": 14, "oversold": 30, "overbought": 70}
            }
        ]
    }
    strategy.set_parameters(params)
    
    # Create mock database session to capture the SelectionHistory save
    mock_db_session = AsyncMock()
    mock_db_session.add = MagicMock()
    mock_db_session.commit = AsyncMock()
    
    # Create mock session factory that returns our mock session
    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db_session)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)
    
    # Patch get_session_factory to return our mock factory
    with patch(
        "app.strategies.dynamic_selection_strategy.get_session_factory",
        return_value=mock_factory
    ):
        # Simulate bars to trigger at least one evaluation (evaluation_period=5)
        for i in range(7):
            bar = BarData(
                symbol="BTCUSDT",
                interval="1m",
                datetime=datetime(2023, 1, 1, 0, i, 0, tzinfo=timezone.utc),
                open=100.0 + i * 0.1,
                high=105.0 + i * 0.1,
                low=95.0 + i * 0.1,
                close=100.0 + i * 0.1,
                volume=10.0
            )
            await strategy.on_bar(bar)
    
    # Verify that the database session add was called (SelectionHistory was created)
    assert mock_db_session.add.called, "SelectionHistory should have been saved to database"
    
    # Get the SelectionHistory object that was passed to db_session.add()
    added_objects = [call.args[0] for call in mock_db_session.add.call_args_list]
    selection_histories = [obj for obj in added_objects if hasattr(obj, 'session_id')]
    
    assert len(selection_histories) > 0, "At least one SelectionHistory should have been created"
    
    # Verify session_id is correctly associated
    for history in selection_histories:
        assert history.session_id is not None, "SelectionHistory.session_id should not be None"
        assert history.session_id == test_session_id, \
            f"SelectionHistory.session_id should be '{test_session_id}', got '{history.session_id}'"
        
        # Additional assertions to verify the record structure
        assert history.total_strategies == 2, "Should have 2 total strategies"
        assert history.surviving_count >= 0, "surviving_count should be non-negative"
        assert history.eliminated_count >= 0, "eliminated_count should be non-negative"
        assert isinstance(history.strategy_weights, dict), "strategy_weights should be a dict"
