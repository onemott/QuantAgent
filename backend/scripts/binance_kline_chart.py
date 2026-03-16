"""
Binance K 线数据获取与可视化脚本
用于获取 Binance K 线数据并绘制图表
"""

import asyncio
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.binance_service import BinanceService


class KlineChartPlotter:
    """K 线图表绘制器"""
    
    def __init__(self):
        self.binance = BinanceService()
    
    async def fetch_and_plot(
        self, 
        symbol: str = "BTC/USDT",
        timeframe: str = "1h",
        limit: int = 100,
        save_path: str = None
    ):
        """
        获取 K 线数据并绘制图表
        
        Args:
            symbol: 交易对
            timeframe: 时间周期
            limit: K 线数量
            save_path: 保存路径（可选）
        """
        print(f"正在获取 {symbol} 的 {timeframe} K 线数据...")
        
        # 获取 K 线数据
        klines = await self.binance.get_klines(symbol, timeframe, limit)
        
        # 转换为 DataFrame
        df = pd.DataFrame([{
            'timestamp': k.timestamp,
            'open': k.open,
            'high': k.high,
            'low': k.low,
            'close': k.close,
            'volume': k.volume
        } for k in klines])
        
        df.set_index('timestamp', inplace=True)
        
        print(f"获取到 {len(df)} 条 K 线数据")
        print(f"时间范围: {df.index[0]} 到 {df.index[-1]}")
        print(f"价格范围: {df['low'].min():.2f} - {df['high'].max():.2f}")
        
        # 绘制图表
        self._plot_candlestick(df, symbol, timeframe, save_path)
        
        return df
    
    def _plot_candlestick(self, df: pd.DataFrame, symbol: str, timeframe: str, save_path: str = None):
        """
        绘制 K 线图
        
        Args:
            df: K 线数据 DataFrame
            symbol: 交易对
            timeframe: 时间周期
            save_path: 保存路径
        """
        # 设置中文字体
        plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans']
        plt.rcParams['axes.unicode_minus'] = False
        
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), 
                                        gridspec_kw={'height_ratios': [3, 1]})
        
        # 绘制 K 线
        for idx, row in df.iterrows():
            color = 'green' if row['close'] >= row['open'] else 'red'
            
            # 绘制实体
            height = abs(row['close'] - row['open'])
            bottom = min(row['close'], row['open'])
            ax1.bar(idx, height, bottom=bottom, color=color, width=0.6, alpha=0.8)
            
            # 绘制影线
            ax1.plot([idx, idx], [row['low'], row['high']], color=color, linewidth=0.8)
        
        # 设置 K 线图标题和标签
        ax1.set_title(f'{symbol} {timeframe} K 线图', fontsize=14, fontweight='bold')
        ax1.set_ylabel('价格 (USDT)', fontsize=12)
        ax1.grid(True, alpha=0.3)
        ax1.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
        
        # 绘制成交量
        colors = ['green' if df['close'].iloc[i] >= df['open'].iloc[i] else 'red' 
                  for i in range(len(df))]
        ax2.bar(df.index, df['volume'], color=colors, width=0.6, alpha=0.7)
        ax2.set_ylabel('成交量', fontsize=12)
        ax2.set_xlabel('时间', fontsize=12)
        ax2.grid(True, alpha=0.3)
        ax2.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
        
        # 旋转 x 轴标签
        plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45)
        plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches='tight')
            print(f"图表已保存到: {save_path}")
        else:
            plt.show()
    
    async def compare_timeframes(self, symbol: str = "BTC/USDT"):
        """
        对比不同时间周期的 K 线
        
        Args:
            symbol: 交易对
        """
        timeframes = ['15m', '1h', '4h', '1d']
        fig, axes = plt.subplots(2, 2, figsize=(16, 12))
        axes = axes.flatten()
        
        for idx, tf in enumerate(timeframes):
            klines = await self.binance.get_klines(symbol, tf, limit=50)
            
            df = pd.DataFrame([{
                'timestamp': k.timestamp,
                'open': k.open,
                'high': k.high,
                'low': k.low,
                'close': k.close,
                'volume': k.volume
            } for k in klines])
            
            df.set_index('timestamp', inplace=True)
            
            ax = axes[idx]
            for _, row in df.iterrows():
                color = 'green' if row['close'] >= row['open'] else 'red'
                height = abs(row['close'] - row['open'])
                bottom = min(row['close'], row['open'])
                ax.bar(_, height, bottom=bottom, color=color, width=0.6, alpha=0.8)
                ax.plot([_, _], [row['low'], row['high']], color=color, linewidth=0.8)
            
            ax.set_title(f'{symbol} {tf}', fontsize=12, fontweight='bold')
            ax.grid(True, alpha=0.3)
        
        plt.suptitle(f'{symbol} 多时间周期对比', fontsize=16, fontweight='bold')
        plt.tight_layout()
        plt.show()


async def main():
    """主函数"""
    plotter = KlineChartPlotter()
    
    print("=" * 60)
    print("Binance K 线数据获取与可视化")
    print("=" * 60)
    
    # 获取并绘制 BTC/USDT 1小时 K 线
    await plotter.fetch_and_plot(
        symbol="BTC/USDT",
        timeframe="1h",
        limit=100,
        save_path="btc_kline_1h.png"
    )
    
    # 获取并绘制 ETH/USDT 4小时 K 线
    print("\n")
    await plotter.fetch_and_plot(
        symbol="ETH/USDT",
        timeframe="4h",
        limit=100,
        save_path="eth_kline_4h.png"
    )
    
    print("\n完成!")


if __name__ == "__main__":
    asyncio.run(main())
