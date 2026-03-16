"""
测试 Binance 连接
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.binance_service import BinanceService


async def test_binance():
    """测试 Binance 连接"""
    service = BinanceService()
    
    print("=" * 60)
    print("测试 Binance API 连接")
    print("=" * 60)
    
    try:
        # 测试获取 Ticker
        print("\n1. 获取 BTC/USDT Ticker...")
        ticker = await service.get_ticker('BTC/USDT')
        print(f"   价格: ${ticker.price:,.2f}")
        print(f"   24h涨跌: {ticker.change_percent:+.2f}%")
        print(f"   24h成交量: {ticker.volume:,.2f}")
        print(f"   24h最高: ${ticker.high_24h:,.2f}")
        print(f"   24h最低: ${ticker.low_24h:,.2f}")
        
        # 测试获取价格
        print("\n2. 获取 ETH/USDT 价格...")
        price = await service.get_price('ETH/USDT')
        print(f"   价格: ${price:,.2f}")
        
        # 测试获取 K 线
        print("\n3. 获取 BTC/USDT 1小时 K 线 (最近5根)...")
        klines = await service.get_klines('BTC/USDT', '1h', limit=5)
        for k in klines:
            print(f"   {k.timestamp.strftime('%Y-%m-%d %H:%M')} - 开: ${k.open:,.2f}, 高: ${k.high:,.2f}, 低: ${k.low:,.2f}, 收: ${k.close:,.2f}")
        
        print("\n✅ 所有测试通过！")
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await service.close()


if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(test_binance())
