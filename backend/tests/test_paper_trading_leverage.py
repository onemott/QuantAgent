import os
import sys
import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.paper_trading_service import PaperTradingService
from app.models.db_models import PaperPosition, PaperTrade


@pytest.mark.asyncio
async def test_apply_fill_does_not_overwrite_existing_leverage_when_none():
    """
    Regression: _apply_fill_to_account(leverage=None) must NOT overwrite an existing
    position leverage with implicit/default 1x during add/open logic.
    """
    svc = PaperTradingService()

    pos = PaperPosition(
        symbol="BTCUSDT",
        session_id=None,
        strategy_id=None,
        quantity=Decimal("1"),
        avg_price=Decimal("100"),
        leverage=10,
        liquidation_price=None,
    )

    svc._get_position = AsyncMock(return_value=pos)
    svc._get_usdt_balance = AsyncMock(return_value=Decimal("100000"))
    svc._update_usdt_balance = AsyncMock()

    with patch("app.services.paper_trading_service.risk_manager") as mock_risk:
        mock_risk.calculate_liquidation_price.return_value = 50.0
        session = AsyncMock()

        await svc._apply_fill_to_account(
            session=session,
            symbol="BTCUSDT",
            side="BUY",
            qty_dec=Decimal("1"),
            price_dec=Decimal("110"),
            fee=Decimal("0"),
            leverage=None,
            strategy_id=None,
            session_id=None,
        )

    assert int(pos.leverage) == 10


@pytest.mark.asyncio
async def test_match_orders_with_bar_price_passes_order_leverage():
    svc = PaperTradingService()

    order = PaperTrade(
        symbol="BTCUSDT",
        side="BUY",
        order_type="LIMIT",
        quantity=Decimal("1"),
        price=Decimal("100"),
        leverage=7,
        fee=Decimal("0"),
        status="NEW",
        mode="historical_replay",
        session_id="S1",
    )

    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.execute = AsyncMock(
        return_value=MagicMock(
            scalars=lambda: MagicMock(all=lambda: [order])
        )
    )

    mock_db = AsyncMock()
    mock_db.__aenter__.return_value = mock_session

    svc._apply_fill_to_account = AsyncMock(
        return_value=(Decimal("0"), Decimal("0"), Decimal("0"))
    )

    with patch("app.services.paper_trading_service.get_db", return_value=mock_db), patch(
        "app.services.paper_trading_service.redis_delete", new=AsyncMock()
    ):
        await svc.match_orders_with_bar_price(
            bar_prices={"BTCUSDT": {"high": 105.0, "low": 95.0, "open": 100.0, "close": 102.0}},
            session_id="S1",
        )

    assert svc._apply_fill_to_account.await_count == 1
    assert svc._apply_fill_to_account.await_args.kwargs["leverage"] == 7


@pytest.mark.asyncio
async def test_match_orders_passes_order_leverage():
    svc = PaperTradingService()

    order = PaperTrade(
        symbol="BTCUSDT",
        side="BUY",
        order_type="LIMIT",
        quantity=Decimal("1"),
        price=Decimal("100"),
        leverage=9,
        fee=Decimal("0"),
        status="NEW",
        mode="paper",
        session_id=None,
    )

    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.execute = AsyncMock(
        return_value=MagicMock(
            scalars=lambda: MagicMock(all=lambda: [order])
        )
    )

    mock_db = AsyncMock()
    mock_db.__aenter__.return_value = mock_session

    svc._apply_fill_to_account = AsyncMock(
        return_value=(Decimal("0"), Decimal("0"), Decimal("0"))
    )

    with patch("app.services.paper_trading_service.get_db", return_value=mock_db), patch(
        "app.services.paper_trading_service.binance_service"
    ) as mock_binance, patch(
        "app.services.paper_trading_service.redis_delete", new=AsyncMock()
    ):
        mock_binance.get_price = AsyncMock(return_value=99.0)  # <= limit -> match
        await svc.match_orders()

    assert svc._apply_fill_to_account.await_count == 1
    assert svc._apply_fill_to_account.await_args.kwargs["leverage"] == 9
