"""
Trading Endpoints - Paper Trading
All endpoints simulate real exchange behavior using virtual USDT balance.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Literal, Optional, List, Dict, Any
from datetime import datetime

from app.services.paper_trading_service import paper_trading_service
from app.services.binance_service import binance_service

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Request / Response Models
# ─────────────────────────────────────────────────────────────────────────────

class OrderRequest(BaseModel):
    symbol: str                              # e.g. "BTCUSDT"
    side: Literal["BUY", "SELL"]
    order_type: Literal["MARKET"] = "MARKET"
    quantity: float
    price: Optional[float] = None            # If None, fetch real-time price


class OrderResponse(BaseModel):
    order_id: str
    symbol: str
    side: str
    order_type: str
    quantity: float
    price: float
    fee: float
    pnl: Optional[float]
    status: str
    created_at: str


# ─────────────────────────────────────────────────────────────────────────────
# Orders
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/orders", response_model=OrderResponse)
async def create_order(order: OrderRequest):
    """
    Place a paper trading order.
    - If price is not provided, fetches real-time price from Binance.
    - BUY deducts USDT; SELL closes position and calculates PnL.
    """
    # Normalize symbol to ccxt format: "BTCUSDT" -> "BTC/USDT"
    symbol_ccxt = _normalize_symbol(order.symbol)

    # Get real-time price if not provided
    if order.price is None:
        try:
            ticker = await binance_service.get_ticker(symbol_ccxt)
            exec_price = ticker.price
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Failed to get price for {order.symbol}: {e}")
    else:
        exec_price = order.price

    try:
        result = await paper_trading_service.create_order(
            symbol=order.symbol.upper(),
            side=order.side,
            quantity=order.quantity,
            price=exec_price,
            order_type=order.order_type,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Order execution failed: {e}")

    return OrderResponse(**result)


@router.get("/orders")
async def get_orders(
    symbol: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """Get order / trade history, newest first."""
    return await paper_trading_service.get_orders(symbol=symbol, limit=limit)


# ─────────────────────────────────────────────────────────────────────────────
# Positions
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/positions")
async def get_positions():
    """
    Get current open positions with real-time PnL.
    Fetches latest prices from Binance for each held symbol.
    """
    # Get positions first (without prices, from cache)
    positions_raw = await paper_trading_service.get_positions()
    if not positions_raw:
        return {"positions": []}

    # Fetch current prices for held symbols
    current_prices: Dict[str, float] = {}
    for pos in positions_raw:
        symbol = pos["symbol"]
        symbol_ccxt = _normalize_symbol(symbol)
        try:
            ticker = await binance_service.get_ticker(symbol_ccxt)
            current_prices[symbol] = ticker.price
        except Exception as e:
            # Fall back to avg_price if Binance unavailable
            current_prices[symbol] = pos["avg_price"]

    # Re-fetch with live prices (bypasses cache)
    positions = await paper_trading_service.get_positions(current_prices=current_prices)
    return {"positions": positions}


@router.post("/positions/close-all")
async def close_all_positions():
    """Close every open position at current market price."""
    positions_raw = await paper_trading_service.get_positions()
    if not positions_raw:
        return {"message": "No open positions", "results": []}

    current_prices: Dict[str, float] = {}
    for pos in positions_raw:
        symbol = pos["symbol"]
        symbol_ccxt = _normalize_symbol(symbol)
        try:
            ticker = await binance_service.get_ticker(symbol_ccxt)
            current_prices[symbol] = ticker.price
        except Exception:
            current_prices[symbol] = pos["avg_price"]

    results = await paper_trading_service.close_all_positions(current_prices)
    return {"message": "Positions closed", "results": results}


# ─────────────────────────────────────────────────────────────────────────────
# Balance
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/balance")
async def get_balance():
    """Get virtual USDT account balance."""
    return await paper_trading_service.get_balance()


@router.get("/risk-status")
async def get_risk_status():
    """Get current account risk metrics and status."""
    from app.services.risk_manager import risk_manager
    
    # Need current portfolio value
    # 1. Balance
    balance_data = await paper_trading_service.get_balance()
    available = balance_data.get("available_balance", 0.0)
    
    # 2. Positions Value (Mark-to-Market)
    positions_raw = await paper_trading_service.get_positions()
    
    # Fetch current prices for accurate equity calculation
    current_prices: Dict[str, float] = {}
    for pos in positions_raw:
        symbol = pos["symbol"]
        symbol_ccxt = _normalize_symbol(symbol)
        try:
            ticker = await binance_service.get_ticker(symbol_ccxt)
            current_prices[symbol] = ticker.price
        except Exception:
            # Fallback to avg_price if fetch fails
            current_prices[symbol] = pos.get("avg_price", 0.0)
            
    # Re-calculate positions with live prices
    positions = await paper_trading_service.get_positions(current_prices=current_prices)
    
    pos_value = 0.0
    for p in positions:
        # Use mark price
        price = p.get("mark_price", p.get("avg_price", 0.0))
        qty = abs(p.get("quantity", 0.0))
        pos_value += qty * price
        
    total_portfolio = available + pos_value
    
    return await risk_manager.get_risk_status(total_portfolio)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_symbol(symbol: str) -> str:
    """Convert 'BTCUSDT' to 'BTC/USDT' for ccxt."""
    symbol = symbol.upper()
    if "/" not in symbol:
        # Common USDT pairs
        for quote in ("USDT", "BTC", "ETH", "BNB", "BUSD"):
            if symbol.endswith(quote):
                base = symbol[: -len(quote)]
                return f"{base}/{quote}"
    return symbol
