import pytest
import asyncio
import json
import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from app.strategies.dynamic_selection_strategy import DynamicSelectionStrategy
from app.core.virtual_bus import VirtualTradingBus, VirtualExecutionRouter
from app.models.trading import BarData, OrderResult, OrderStatus, OrderRequest, TradeSide, OrderType
from app.services.strategy_runner_service import NATSTradingBus, NATS_ORDER_SIGNAL_TOPIC, StrategyRunnerService

class DummyBus:
    def __init__(self):
        self.orders = []
        self.balance = {"available_balance": 10000.0}
        
    async def execute_order(self, req):
        self.orders.append(req)
        return OrderResult(
            order_id="test_id",
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
async def test_dynamic_selection_strategy_init_and_params():
    bus = DummyBus()
    strategy = DynamicSelectionStrategy(strategy_id="test_dyn", bus=bus)
    
    params = {
        "initial_capital": 10000.0,
        "composition_threshold": 0.5,
        "evaluation_period": 10,
        "weight_method": "equal",
        "atomic_strategies": [
            {
                "strategy_id": "s1",
                "strategy_type": "ma",
                "params": {"fast_period": 5, "slow_period": 10}
            },
            {
                "strategy_id": "s2",
                "strategy_type": "rsi",
                "params": {"rsi_period": 14, "oversold": 30, "overbought": 70}
            }
        ]
    }
    
    strategy.set_parameters(params)
    
    assert len(strategy.alive_strategies) == 2
    assert "s1" in strategy.alive_strategies
    assert "s2" in strategy.alive_strategies
    assert len(strategy.virtual_buses) == 2
    assert strategy.composer.threshold == 0.5
    assert strategy.evaluation_period == 10

@pytest.mark.asyncio
async def test_dynamic_selection_on_bar_dispatch():
    bus = DummyBus()
    strategy = DynamicSelectionStrategy(strategy_id="test_dyn", bus=bus)
    
    params = {
        "atomic_strategies": [
            {
                "strategy_id": "s1",
                "strategy_type": "ma",
                "params": {"fast_period": 2, "slow_period": 5}
            }
        ],
        "evaluation_period": 5
    }
    strategy.set_parameters(params)
    
    # Send some bars
    for i in range(3):
        bar = BarData(
            symbol="BTCUSDT",
            interval="1h",
            datetime=datetime.now(timezone.utc),
            open=100.0 + i,
            high=105.0 + i,
            low=95.0 + i,
            close=100.0 + i,
            volume=10.0
        )
        await strategy.on_bar(bar)
        
    assert strategy.bar_count == 3
    # check that virtual bus has the current bar
    assert strategy.virtual_buses["s1"].router.current_bar.close == 102.0

@pytest.mark.asyncio
async def test_dynamic_selection_signal_composition_and_execution():
    bus = DummyBus()
    strategy = DynamicSelectionStrategy(strategy_id="test_dyn", bus=bus)
    
    params = {
        "atomic_strategies": [
            {
                "strategy_id": "s1",
                "strategy_type": "ma"
            }
        ],
        "evaluation_period": 100,
        "initial_capital": 10000.0
    }
    strategy.set_parameters(params)
    
    # manually set virtual position
    strategy.virtual_buses["s1"].router.position = 1.0
    
    # on next bar, the composed signal should be 1
    bar = BarData(
        symbol="BTCUSDT",
        interval="1h",
        datetime=datetime.now(timezone.utc),
        open=100.0,
        high=100.0,
        low=100.0,
        close=100.0,
        volume=10.0
    )
    
    await strategy.on_bar(bar)
    
    # bus should receive a BUY order
    assert len(bus.orders) == 1
    assert bus.orders[0].side.value == "BUY"
    assert strategy.current_position > 0
    
    # now set virtual position to 0 (which means strategy closed its position)
    strategy.virtual_buses["s1"].router.position = 0.0
    
    await strategy.on_bar(bar)
    
    # bus should receive a SELL order
    assert len(bus.orders) == 2
    assert bus.orders[1].side.value == "SELL"
    assert strategy.current_position == 0.0


# =====================================================
# New tests for Bug Fix Verification
# =====================================================

# a) NATSTradingBus 可正常实例化
def test_nats_trading_bus_instantiation():
    """Test that NATSTradingBus can be instantiated with nc=None without TypeError."""
    bus = NATSTradingBus(nc=None, session_id="test_session", symbol="BTCUSDT", quantity=0.01)
    
    assert bus.session_id == "test_session"
    assert bus.symbol == "BTCUSDT"
    assert bus.quantity == 0.01
    assert bus.get_mode() == "PAPER"


# b) 标的不一致时 set_parameters 记录警告
@pytest.mark.asyncio
async def test_symbol_mismatch_logs_warning(caplog):
    """Test that set_parameters logs a warning when atomic_strategies have different symbols."""
    bus = DummyBus()
    strategy = DynamicSelectionStrategy(strategy_id="test_dyn", bus=bus)
    
    params = {
        "initial_capital": 10000.0,
        "atomic_strategies": [
            {
                "strategy_id": "s1",
                "strategy_type": "ma",
                "symbol": "BTCUSDT",
                "params": {"fast_period": 5, "slow_period": 10}
            },
            {
                "strategy_id": "s2",
                "strategy_type": "rsi",
                "symbol": "ETHUSDT",  # Different symbol
                "params": {"rsi_period": 14}
            }
        ]
    }
    
    with caplog.at_level(logging.WARNING):
        strategy.set_parameters(params)
    
    # Check that warning was logged for symbol mismatch
    assert any("Symbol mismatch" in record.message for record in caplog.records)


# c) equity_curve 超过上限后被正确裁剪
def test_equity_curve_trimming():
    """Test that equity_curve is trimmed when exceeding max_equity_curve_size."""
    router = VirtualExecutionRouter(initial_capital=10000, max_equity_curve_size=100)
    
    # Feed more than 100 bars
    for i in range(150):
        bar = BarData(
            symbol="BTCUSDT",
            interval="1h",
            datetime=datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc) + __import__('datetime').timedelta(hours=i),
            open=100.0,
            high=105.0,
            low=95.0,
            close=100.0 + i * 0.1,
            volume=10.0
        )
        router.set_current_bar(bar)
    
    # After trimming, equity_curve should not exceed the limit
    assert len(router.equity_curve) <= 100


# d) NATS 主题与 Go 端一致
def test_nats_topic_constant():
    """Test that NATS_ORDER_SIGNAL_TOPIC matches the Go gateway subscription."""
    assert NATS_ORDER_SIGNAL_TOPIC == "signal.order"


# e) 消息体结构正确
@pytest.mark.asyncio
async def test_nats_message_structure():
    """Test that NATS message payload has correct structure (source field, no order_type/client_order_id)."""
    mock_nc = AsyncMock()
    bus = NATSTradingBus(nc=mock_nc, session_id="test_session", symbol="BTCUSDT", quantity=0.01)
    
    order_req = OrderRequest(
        symbol="BTCUSDT",
        side=TradeSide.BUY,
        quantity=0.05,
        price=50000.0,
        order_type=OrderType.MARKET,
        strategy_id="test_strategy"
    )
    
    await bus.execute_order(order_req)
    
    # Verify mock_nc.publish was called
    assert mock_nc.publish.called
    
    # Get the call arguments
    call_args = mock_nc.publish.call_args
    topic = call_args[0][0]
    payload_bytes = call_args[0][1]
    payload = json.loads(payload_bytes.decode())
    
    # Verify topic
    assert topic == "signal.order"
    
    # Verify payload has 'source' field (not 'strategy_id')
    assert "source" in payload
    assert payload["source"] == "test_strategy"
    assert "strategy_id" not in payload
    
    # Verify payload does NOT have order_type or client_order_id
    assert "order_type" not in payload
    assert "client_order_id" not in payload
    
    # Verify required fields
    assert payload["symbol"] == "BTCUSDT"
    assert payload["side"] == "BUY"
    assert payload["quantity"] == 0.05


# f) quantity 使用策略计算值
@pytest.mark.asyncio
async def test_quantity_uses_strategy_calculated_value():
    """Test that execute_order returns filled_quantity from order_req.quantity, not hardcoded self.quantity."""
    mock_nc = AsyncMock()
    bus = NATSTradingBus(nc=mock_nc, session_id="test_session", symbol="BTCUSDT", quantity=0.01)
    
    # Request quantity different from bus default
    order_req = OrderRequest(
        symbol="BTCUSDT",
        side=TradeSide.BUY,
        quantity=0.05,  # Different from bus.quantity=0.01
        price=50000.0,
        order_type=OrderType.MARKET,
        strategy_id="test_strategy"
    )
    
    result = await bus.execute_order(order_req)
    
    # Verify filled_quantity uses order_req.quantity
    assert result.filled_quantity == 0.05
    assert result.filled_quantity != bus.quantity  # Should be different from hardcoded quantity


# g) 同一根 bar 不触发重复 on_bar
@pytest.mark.asyncio
async def test_same_bar_no_duplicate_on_bar():
    """Test that the same bar time does not trigger duplicate on_bar calls."""
    service = StrategyRunnerService()
    service.is_warmed_up = True
    
    # Mock the strategy
    mock_strategy = AsyncMock()
    service.strategy = mock_strategy
    
    # Set last_bar_time
    bar_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    service.last_bar_time = bar_time
    
    # Create a bar with the same time
    same_bar = BarData(
        symbol="BTCUSDT",
        interval="1h",
        datetime=bar_time,  # Same as last_bar_time
        open=100.0,
        high=105.0,
        low=95.0,
        close=100.0,
        volume=10.0
    )
    
    # Mock binance_service to return data with the same bar time
    with patch('app.services.strategy_runner_service.binance_service') as mock_binance:
        import pandas as pd
        df = pd.DataFrame({
            'open': [100.0],
            'high': [105.0],
            'low': [95.0],
            'close': [100.0],
            'volume': [10.0]
        }, index=[bar_time])
        mock_binance.get_klines_dataframe = AsyncMock(return_value=df)
        
        await service.run_all_strategies()
    
    # Strategy.on_bar should NOT be called since bar time is same as last_bar_time
    mock_strategy.on_bar.assert_not_called()
