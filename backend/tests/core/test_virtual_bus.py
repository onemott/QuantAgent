import pytest
import pytest_asyncio
from datetime import datetime, timedelta
import pandas as pd

from app.core.virtual_bus import VirtualExecutionRouter, VirtualTradingBus, VirtualPerformanceMetric
from app.models.trading import BarData, OrderRequest, TradeSide, OrderType, OrderStatus

@pytest.fixture
def base_time():
    return datetime(2023, 1, 1, 0, 0, 0)

@pytest.fixture
def router():
    return VirtualExecutionRouter(initial_capital=10000.0, slippage_pct=0.001, fee_rate=0.001)

@pytest.fixture
def bus():
    return VirtualTradingBus(initial_capital=10000.0)

@pytest.mark.asyncio
async def test_virtual_router_buy_sell(router, base_time):
    # Set current bar
    bar1 = BarData(symbol="BTCUSDT", datetime=base_time, open=100.0, high=100.0, low=100.0, close=100.0, volume=10.0, interval="1m")
    router.set_current_bar(bar1)
    
    assert router.get_equity() == 10000.0
    
    # Buy 10 units at 100
    order1 = OrderRequest(symbol="BTCUSDT", side=TradeSide.BUY, order_type=OrderType.MARKET, quantity=10.0, strategy_id="test")
    res1 = await router.execute(order1)
    
    assert res1.status == OrderStatus.FILLED
    # Price = 100 * (1 + 0.001) = 100.1
    assert res1.filled_price == pytest.approx(100.1)
    # Fee = 10 * 100.1 * 0.001 = 1.001
    assert res1.fee == pytest.approx(1.001)
    
    assert router.position == pytest.approx(10.0)
    assert router.cash == pytest.approx(10000.0 - (10.0 * 100.1 + 1.001))
    
    # Equity = cash + position * close
    assert router.get_equity() == pytest.approx(router.cash + 10.0 * 100.0)
    
    # Next bar, price goes to 110
    bar2 = BarData(symbol="BTCUSDT", datetime=base_time + timedelta(minutes=1), open=110.0, high=110.0, low=110.0, close=110.0, volume=10.0, interval="1m")
    router.set_current_bar(bar2)
    
    assert router.get_equity() == pytest.approx(router.cash + 10.0 * 110.0)
    
    # Sell 10 units at 110
    order2 = OrderRequest(symbol="BTCUSDT", side=TradeSide.SELL, order_type=OrderType.MARKET, quantity=10.0, strategy_id="test")
    res2 = await router.execute(order2)
    
    assert res2.status == OrderStatus.FILLED
    # Price = 110 * (1 - 0.001) = 109.89
    assert res2.filled_price == pytest.approx(109.89)
    # Fee = 10 * 109.89 * 0.001 = 1.0989
    assert res2.fee == pytest.approx(1.0989)
    
    assert router.position == pytest.approx(0.0)
    assert router.get_equity() == pytest.approx(router.cash)  # Position is 0
    
    assert router.trade_count == 2
    assert router.winning_trades == 1  # The sell was profitable

@pytest.mark.asyncio
async def test_virtual_bus(bus, base_time):
    assert bus.get_mode() == "VIRTUAL"
    
    bar = BarData(symbol="BTCUSDT", datetime=base_time, open=100.0, high=100.0, low=100.0, close=100.0, volume=10.0, interval="1m")
    await bus.publish_bar(bar)
    
    balance = await bus.get_balance()
    assert balance["total_balance"] == 10000.0
    assert balance["available_balance"] == 10000.0
    
    order = OrderRequest(symbol="BTCUSDT", side=TradeSide.BUY, order_type=OrderType.MARKET, quantity=10.0, strategy_id="test")
    await bus.execute_order(order)
    
    balance = await bus.get_balance()
    assert balance["total_balance"] < 10000.0  # Due to slippage and fee
    assert balance["available_balance"] < 10000.0

@pytest.mark.asyncio
async def test_performance_metric(router, base_time):
    # Simulate a series of bars and trades
    prices = [100, 110, 90, 120]
    
    for i, p in enumerate(prices):
        dt = base_time + timedelta(days=i)
        bar = BarData(symbol="BTCUSDT", datetime=dt, open=p, high=p, low=p, close=p, volume=10.0, interval="1d")
        router.set_current_bar(bar)
        
        if i == 0:
            # Buy
            order = OrderRequest(symbol="BTCUSDT", side=TradeSide.BUY, order_type=OrderType.MARKET, quantity=10.0, strategy_id="test")
            await router.execute(order)
        elif i == 3:
            # Sell
            order = OrderRequest(symbol="BTCUSDT", side=TradeSide.SELL, order_type=OrderType.MARKET, quantity=10.0, strategy_id="test")
            await router.execute(order)
            
    metric = router.get_performance_metric()
    assert metric.total_trades == 2
    assert metric.win_rate == 0.5  # 1 winning trade / 2 total trades
    
    # Basic checks to ensure metrics are calculated
    assert metric.total_return != 0
    assert metric.annualized_return != 0
    assert metric.max_drawdown_pct > 0
    assert metric.volatility > 0
    
    # Check property types
    assert isinstance(metric.annualized_return, float)
    assert isinstance(metric.max_drawdown_pct, float)
    assert isinstance(metric.sharpe_ratio, float)
    assert isinstance(metric.win_rate, float)
    assert isinstance(metric.total_trades, int)
    assert isinstance(metric.total_return, float)
    assert isinstance(metric.volatility, float)
    assert isinstance(metric.sortino_ratio, float)
    assert isinstance(metric.calmar_ratio, float)
