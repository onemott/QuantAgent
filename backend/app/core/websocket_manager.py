"""
WebSocket Connection Manager
"""
from fastapi import WebSocket
from typing import Dict, Set
import asyncio
import logging
import json

logger = logging.getLogger(__name__)

class MarketWebSocketManager:
    """
    Manages WebSocket connections and per-symbol subscriptions.
    Pushes real-time ticker updates to subscribed clients.
    """

    def __init__(self):
        # ws -> set of subscribed symbols
        self._connections: Dict[WebSocket, Set[str]] = {}
        self._price_task: asyncio.Task | None = None

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._connections[ws] = set()
        logger.info(f"WS connected. Total: {len(self._connections)}")

    async def disconnect(self, ws: WebSocket):
        self._connections.pop(ws, None)
        logger.info(f"WS disconnected. Total: {len(self._connections)}")

    async def subscribe(self, ws: WebSocket, symbol: str):
        if ws in self._connections:
            self._connections[ws].add(symbol.upper())

    async def unsubscribe(self, ws: WebSocket, symbol: str):
        if ws in self._connections:
            self._connections[ws].discard(symbol.upper())

    def get_all_symbols(self) -> Set[str]:
        symbols: Set[str] = set()
        for subs in self._connections.values():
            symbols.update(subs)
        return symbols

    async def broadcast_ticker(self, symbol: str, data: dict):
        dead = []
        for ws, subs in self._connections.items():
            if symbol in subs:
                try:
                    await ws.send_json(data)
                except Exception:
                    dead.append(ws)
        for ws in dead:
            await self.disconnect(ws)

    def start_price_loop(self):
        if self._price_task is None or self._price_task.done():
            self._price_task = asyncio.create_task(self._price_push_loop())

    def stop_price_loop(self):
        if self._price_task and not self._price_task.done():
            self._price_task.cancel()

    async def _price_push_loop(self):
        """Background task: fetch prices and push every 1 second (Legacy Polling)."""
        # This imports binance_service inside to avoid circular dependency
        from app.services.binance_service import binance_service

        logger.info("WebSocket price push loop started.")
        while True:
            try:
                symbols = self.get_all_symbols()
                for symbol in symbols:
                    # Convert BTCUSDT -> BTC/USDT for ccxt
                    ccxt_sym = _ccxt_symbol(symbol)
                    try:
                        ticker = await binance_service.get_ticker(ccxt_sym)
                        await self.broadcast_ticker(symbol, {
                            "type":           "ticker",
                            "symbol":         symbol,
                            "price":          ticker.price,
                            "change_24h":     ticker.change_24h,
                            "change_percent": ticker.change_percent,
                            "volume":         ticker.volume,
                            "high_24h":       ticker.high_24h,
                            "low_24h":        ticker.low_24h,
                        })
                    except Exception as e:
                        logger.debug(f"Failed to fetch ticker for {symbol}: {e}")
            except Exception as e:
                logger.error(f"Price push loop error: {e}")
            await asyncio.sleep(1)

def _ccxt_symbol(symbol: str) -> str:
    """Convert 'BTCUSDT' to 'BTC/USDT'."""
    symbol = symbol.upper()
    if "/" not in symbol:
        for quote in ("USDT", "BTC", "ETH", "BNB", "BUSD"):
            if symbol.endswith(quote):
                base = symbol[: -len(quote)]
                return f"{base}/{quote}"
    return symbol

ws_manager = MarketWebSocketManager()
