"""
测试 Market Analysis Service
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.market_analysis_service import MarketAnalysisService

async def test_analysis():
    print("Initializing service...")
    try:
        # Use provider from environment settings
        from app.core.config import settings
        provider = settings.LLM_PROVIDER
        service = MarketAnalysisService(provider_name=provider)
        print(f"Service initialized ({provider}).")
        
        print("Analyzing BTC/USDT...")
        result = await service.analyze_market("BTC/USDT")
        print(f"Result: {result[:100]}...")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(test_analysis())
