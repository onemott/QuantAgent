"""
价格对比脚本
对比 Binance 和 CoinGecko 的价格差异
"""

import asyncio
import sys
import os
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.binance_service import BinanceService
from app.services.coingecko_service import CoinGeckoService


async def compare_prices():
    """对比多个币种的价格"""
    binance = BinanceService()
    coingecko = CoinGeckoService()
    
    # 要对比的币种
    symbols = [
        ("BTC/USDT", "bitcoin", "BTC"),
        ("ETH/USDT", "ethereum", "ETH"),
        ("SOL/USDT", "solana", "SOL"),
        ("BNB/USDT", "binancecoin", "BNB"),
        ("XRP/USDT", "ripple", "XRP"),
    ]
    
    print("=" * 80)
    print(f"{'币种':<10} {'Binance':<15} {'CoinGecko':<15} {'差价':<15} {'差价%':<10}")
    print("=" * 80)
    
    results = []
    
    for binance_symbol, coin_id, display_symbol in symbols:
        try:
            # 获取 Binance 价格
            binance_price = await binance.get_price(binance_symbol)
        except Exception as e:
            print(f"{display_symbol:<10} 获取 Binance 价格失败: {e}")
            binance_price = None
        
        try:
            # 获取 CoinGecko 价格
            coingecko_price = coingecko.get_price(coin_id, 'usd')
        except Exception as e:
            print(f"{display_symbol:<10} 获取 CoinGecko 价格失败: {e}")
            coingecko_price = None
        
        # 计算差价
        if binance_price and coingecko_price:
            diff = abs(binance_price - coingecko_price)
            diff_percent = (diff / ((binance_price + coingecko_price) / 2)) * 100
            
            print(f"{display_symbol:<10} ${binance_price:<14.2f} ${coingecko_price:<14.2f} ${diff:<14.4f} {diff_percent:<10.4f}%")
            
            results.append({
                'symbol': display_symbol,
                'binance': binance_price,
                'coingecko': coingecko_price,
                'diff': diff,
                'diff_percent': diff_percent
            })
        else:
            print(f"{display_symbol:<10} {'N/A':<15} {'N/A':<15} {'N/A':<15} {'N/A':<10}")
    
    print("=" * 80)
    
    # 输出统计信息
    if results:
        avg_diff = sum(r['diff_percent'] for r in results) / len(results)
        max_diff = max(results, key=lambda x: x['diff_percent'])
        min_diff = min(results, key=lambda x: x['diff_percent'])
        
        print(f"\n统计信息:")
        print(f"  平均差价: {avg_diff:.4f}%")
        print(f"  最大差价: {max_diff['symbol']} ({max_diff['diff_percent']:.4f}%)")
        print(f"  最小差价: {min_diff['symbol']} ({min_diff['diff_percent']:.4f}%)")
    
    return results


async def get_market_overview():
    """获取 CoinGecko 市场概览"""
    coingecko = CoinGeckoService()
    
    print("\n" + "=" * 80)
    print("CoinGecko 市场概览 (Top 10)")
    print("=" * 80)
    print(f"{'排名':<6} {'币种':<15} {'价格':<15} {'24h涨跌':<12} {'市值':<20}")
    print("-" * 80)
    
    try:
        markets = coingecko.get_market_overview(per_page=10)
        
        for market in markets:
            rank = market.market_cap_rank or "N/A"
            name = market.name[:14]
            price = f"${market.current_price:,.2f}"
            change = f"{market.price_change_percentage_24h:+.2f}%" if market.price_change_percentage_24h else "N/A"
            market_cap = f"${market.market_cap:,.0f}" if market.market_cap else "N/A"
            
            print(f"{rank:<6} {name:<15} {price:<15} {change:<12} {market_cap:<20}")
    except Exception as e:
        print(f"获取市场概览失败: {e}")
    
    print("=" * 80)


async def get_trending():
    """获取热门币种"""
    coingecko = CoinGeckoService()
    
    print("\n" + "=" * 80)
    print("CoinGecko 热门币种 (Trending)")
    print("=" * 80)
    
    try:
        trending = coingecko.get_trending_coins()
        
        for idx, coin in enumerate(trending[:5], 1):
            item = coin['item']
            print(f"{idx}. {item['name']} ({item['symbol']}) - 市值排名: #{item['market_cap_rank']}")
    except Exception as e:
        print(f"获取热门币种失败: {e}")
    
    print("=" * 80)


async def main():
    """主函数"""
    print("\n")
    print("╔" + "=" * 78 + "╗")
    print("║" + " " * 20 + "加密货币价格对比工具" + " " * 38 + "║")
    print("╚" + "=" * 78 + "╝")
    print(f"\n执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # 1. 价格对比
    await compare_prices()
    
    # 2. 市场概览
    await get_market_overview()
    
    # 3. 热门币种
    await get_trending()
    
    print("\n✅ 数据获取完成!")


if __name__ == "__main__":
    asyncio.run(main())
