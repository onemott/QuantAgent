"""
CoinGecko Data Service
提供 CoinGecko 市场数据获取功能
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from pycoingecko import CoinGeckoAPI
from app.core.config import settings, get_proxies
from app.models.market_data import MarketOverview, PriceComparison


import logging

logger = logging.getLogger(__name__)

class CoinGeckoService:
    """CoinGecko 数据服务类"""
    
    def __init__(self):
        """初始化 CoinGecko API 连接"""
        self.api_key = settings.COINGECKO_API_KEY
        self.base_url = "https://api.coingecko.com/api/v3"
        
        # CoinGecko is an external API that may be blocked in restricted regions.
        # Use explicit proxies dict; do NOT touch global env variables.
        self.proxies = get_proxies()
        if self.proxies:
            logger.info(f"CoinGeckoService: using explicit proxy {self.proxies}")
        
        # 使用 pycoingecko 库（演示版 API）
        self.cg = CoinGeckoAPI(demo_api_key=self.api_key)
    
    def _get_headers(self) -> Dict[str, str]:
        """获取 API 请求头"""
        headers = {}
        if self.api_key:
            headers['x-cg-demo-api-key'] = self.api_key
        return headers
    
    def get_price(self, coin_id: str = "bitcoin", vs_currency: str = "usd") -> float:
        """
        获取指定币种的当前价格
        
        Args:
            coin_id: CoinGecko 币种 ID，如 "bitcoin", "ethereum"
            vs_currency: 计价货币，如 "usd", "cny"
            
        Returns:
            float: 当前价格
        """
        try:
            url = f"{self.base_url}/simple/price"
            params = {
                'ids': coin_id,
                'vs_currencies': vs_currency
            }
            
            response = requests.get(url, params=params, headers=self._get_headers(), proxies=self.proxies)
            response.raise_for_status()
            data = response.json()
            
            return float(data[coin_id][vs_currency])
        except Exception as e:
            raise Exception(f"Failed to fetch price for {coin_id}: {str(e)}")
    
    def get_market_overview(
        self, 
        vs_currency: str = "usd", 
        per_page: int = 100, 
        page: int = 1
    ) -> List[MarketOverview]:
        """
        获取市场概览数据（市值排名、价格、涨跌幅等）
        
        Args:
            vs_currency: 计价货币
            per_page: 每页数量
            page: 页码
            
        Returns:
            List[MarketOverview]: 市场概览数据列表
        """
        try:
            url = f"{self.base_url}/coins/markets"
            params = {
                'vs_currency': vs_currency,
                'order': 'market_cap_desc',
                'per_page': per_page,
                'page': page,
                'sparkline': 'false'
            }
            
            response = requests.get(url, params=params, headers=self._get_headers(), proxies=self.proxies)
            response.raise_for_status()
            data = response.json()
            
            markets = []
            for item in data:
                markets.append(MarketOverview(
                    id=item['id'],
                    symbol=item['symbol'].upper(),
                    name=item['name'],
                    current_price=float(item['current_price'] or 0),
                    market_cap=float(item['market_cap'] or 0) if item['market_cap'] else None,
                    market_cap_rank=item['market_cap_rank'],
                    price_change_24h=float(item['price_change_24h'] or 0) if item['price_change_24h'] else None,
                    price_change_percentage_24h=float(item['price_change_percentage_24h'] or 0) if item['price_change_percentage_24h'] else None,
                    total_volume=float(item['total_volume'] or 0) if item['total_volume'] else None,
                    last_updated=datetime.fromisoformat(item['last_updated'].replace('Z', '+00:00')) if item['last_updated'] else None
                ))
            
            return markets
        except Exception as e:
            raise Exception(f"Failed to fetch market overview: {str(e)}")
    
    def get_coin_history(
        self, 
        coin_id: str = "bitcoin", 
        vs_currency: str = "usd", 
        days: int = 30
    ) -> pd.DataFrame:
        """
        获取币种历史价格数据
        
        Args:
            coin_id: 币种 ID
            vs_currency: 计价货币
            days: 天数（1, 7, 14, 30, 90, 180, 365, max）
            
        Returns:
            pd.DataFrame: 历史价格数据
        """
        try:
            url = f"{self.base_url}/coins/{coin_id}/market_chart"
            params = {
                'vs_currency': vs_currency,
                'days': days
            }
            
            response = requests.get(url, params=params, headers=self._get_headers(), proxies=self.proxies)
            response.raise_for_status()
            data = response.json()
            
            # 处理价格数据
            prices = data.get('prices', [])
            market_caps = data.get('market_caps', [])
            volumes = data.get('total_volumes', [])
            
            df_data = []
            for i, price_item in enumerate(prices):
                timestamp = datetime.fromtimestamp(price_item[0] / 1000)
                price = price_item[1]
                market_cap = market_caps[i][1] if i < len(market_caps) else None
                volume = volumes[i][1] if i < len(volumes) else None
                
                df_data.append({
                    'timestamp': timestamp,
                    'price': price,
                    'market_cap': market_cap,
                    'volume': volume
                })
            
            df = pd.DataFrame(df_data)
            df.set_index('timestamp', inplace=True)
            
            return df
        except Exception as e:
            raise Exception(f"Failed to fetch history for {coin_id}: {str(e)}")
    
    def get_coin_info(self, coin_id: str = "bitcoin") -> Dict[str, Any]:
        """
        获取币种详细信息
        
        Args:
            coin_id: 币种 ID
            
        Returns:
            Dict: 币种详细信息
        """
        try:
            url = f"{self.base_url}/coins/{coin_id}"
            params = {
                'localization': 'false',
                'tickers': 'false',
                'market_data': 'true',
                'community_data': 'false',
                'developer_data': 'false'
            }
            
            response = requests.get(url, params=params, headers=self._get_headers(), proxies=self.proxies)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            raise Exception(f"Failed to fetch coin info for {coin_id}: {str(e)}")
    
    def search_coins(self, query: str) -> List[Dict[str, Any]]:
        """
        搜索币种
        
        Args:
            query: 搜索关键词
            
        Returns:
            List[Dict]: 匹配的币种列表
        """
        try:
            url = f"{self.base_url}/search"
            params = {'query': query}
            
            response = requests.get(url, params=params, headers=self._get_headers(), proxies=self.proxies)
            response.raise_for_status()
            data = response.json()
            
            return data.get('coins', [])
        except Exception as e:
            raise Exception(f"Failed to search coins: {str(e)}")
    
    def get_trending_coins(self) -> List[Dict[str, Any]]:
        """
        获取 trending（热门）币种
        
        Returns:
            List[Dict]: 热门币种列表
        """
        try:
            url = f"{self.base_url}/search/trending"
            
            response = requests.get(url, headers=self._get_headers(), proxies=self.proxies)
            response.raise_for_status()
            data = response.json()
            
            return data.get('coins', [])
        except Exception as e:
            raise Exception(f"Failed to fetch trending coins: {str(e)}")
    
    def compare_price(
        self, 
        symbol: str = "BTC", 
        binance_price: Optional[float] = None
    ) -> PriceComparison:
        """
        对比 Binance 和 CoinGecko 的价格
        
        Args:
            symbol: 交易对符号，如 "BTC"
            binance_price: Binance 价格（可选）
            
        Returns:
            PriceComparison: 价格对比结果
        """
        # 将 symbol 转换为 coin_id
        # 预处理：移除常见后缀
        clean_symbol = symbol.upper()
        for suffix in ["USDT", "USDC", "BUSD", "USD"]:
            if clean_symbol.endswith(suffix) and len(clean_symbol) > len(suffix):
                clean_symbol = clean_symbol[:-len(suffix)]
                break
        
        symbol_to_id = {
            'BTC': 'bitcoin',
            'ETH': 'ethereum',
            'SOL': 'solana',
            'BNB': 'binancecoin',
            'XRP': 'ripple',
            'ADA': 'cardano',
            'DOGE': 'dogecoin',
            'DOT': 'polkadot',
            'MATIC': 'matic-network',
            'LINK': 'chainlink'
        }
        
        coin_id = symbol_to_id.get(clean_symbol, clean_symbol.lower())
        
        # 特殊处理
        if clean_symbol == 'MATIC':
             coin_id = 'matic-network'

        
        try:
            coingecko_price = self.get_price(coin_id, 'usd')
        except Exception as e:
            logger.error(f"Error fetching CoinGecko price for {coin_id}: {e}")
            coingecko_price = None
        
        price_diff = None
        price_diff_percent = None
        
        if binance_price and coingecko_price:
            price_diff = abs(binance_price - coingecko_price)
            price_diff_percent = (price_diff / ((binance_price + coingecko_price) / 2)) * 100
        
        return PriceComparison(
            symbol=symbol,
            binance_price=binance_price,
            coingecko_price=coingecko_price,
            price_diff=price_diff,
            price_diff_percent=price_diff_percent,
            timestamp=datetime.now()
        )


# 单例实例
coingecko_service = CoinGeckoService()
