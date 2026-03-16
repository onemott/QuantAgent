"""
API V1 Router
"""

from fastapi import APIRouter

from app.api.v1.endpoints import market, trading, auth, strategy, analytics, risk

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(market.router, prefix="/market", tags=["Market Data"])
api_router.include_router(trading.router, prefix="/trading", tags=["Trading"])
api_router.include_router(risk.router, prefix="/risk", tags=["Risk Management"])
api_router.include_router(strategy.router, prefix="/strategy", tags=["Strategy"])
api_router.include_router(analytics.router, prefix="/analytics", tags=["Analytics"])
