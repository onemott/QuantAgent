"""
基于信号的策略适配器
将 strategy_templates 中的信号函数封装到 BaseStrategy 接口中。
支持所有策略类型：ma, rsi, boll, macd, ema_triple, atr_trend, turtle, ichimoku

注意：smart_beta 和 basis 是需要实时宏观数据的异步策略，
      不适合历史回放。它们已被排除。
"""

import logging
import pandas as pd
import inspect
from typing import Dict, Any, Optional
from app.core.strategy import BaseStrategy
from app.models.trading import BarData, OrderRequest, TradeSide, OrderType
from app.services.strategy_templates import build_signal_func

logger = logging.getLogger(__name__)

# 需要实时外部数据的异步策略（不适合回测）
ASYNC_STRATEGIES = {"smart_beta", "basis"}

class SignalBasedStrategy(BaseStrategy):
    """
    通用信号型策略适配器，用于封装 strategy_templates 中的信号函数。
    不同策略类型（如 ma、rsi、boll 等）会基于技术指标生成交易信号。
    """
    def __init__(self, strategy_id: str, bus: 'TradingBus', strategy_type: str = "ma"):
        super().__init__(strategy_id, bus)
        self.strategy_type = strategy_type
        self.bars = []
        self.position = 0.0
        self._signal_func = None
        
        # 检查策略是否为异步（不适合历史回放）
        if strategy_type in ASYNC_STRATEGIES:
            self.log(f"策略 {strategy_type} 是异步策略，不适合历史回放", "WARNING")
        
    def set_parameters(self, params: Dict[str, Any]):
        super().set_parameters(params)
        # 跳过异步策略（需要实时数据）
        if self.strategy_type in ASYNC_STRATEGIES:
            self.log(f"跳过异步策略: {self.strategy_type}", "WARNING")
            self._signal_func = None
            return
            
        # 构建带有固化参数的信号函数
        try:
            self._signal_func = build_signal_func(self.strategy_type, params)
            # 验证信号函数是否为同步（非异步）
            if inspect.iscoroutinefunction(self._signal_func):
                self.log(f"策略 {self.strategy_type} 是异步的，跳过", "WARNING")
                self._signal_func = None
        except Exception as e:
            self.log(f"构建信号函数失败: {e}", "ERROR")
            self._signal_func = None

    async def on_bar(self, bar: BarData):
        self.bars.append(bar)
        
        # 保留足够的K线数据（最多200根以确保安全）
        max_period = 200
        if len(self.bars) > max_period:
            self.bars.pop(0)

        # 指标计算需要最小K线数量
        min_bars = self._get_min_bars_required()
        if len(self.bars) < min_bars:
            return
        
        # 首次达到最小K线阈值时记录一次
        if len(self.bars) == min_bars:
            logger.info(f"[策略:{self.strategy_id}] 已达到最小K线数量 ({min_bars})，开始生成信号")

        # 生成信号
        if self._signal_func is None:
            return
            
        try:
            # 将K线数据转换为DataFrame用于指标计算
            df = pd.DataFrame([{
                'timestamp': b.datetime,
                'open': b.open,
                'high': b.high,
                'low': b.low,
                'close': b.close,
                'volume': getattr(b, 'volume', 0)
            } for b in self.bars])
            df.set_index('timestamp', inplace=True)
            
            # 生成信号
            signal = self._signal_func(df)
            
            if signal is None or len(signal) == 0:
                return
                
            current_signal = signal.iloc[-1]
            
            # 记录非零信号
            if current_signal != 0:
                logger.info(f"[策略:{self.strategy_id}] 信号={current_signal} 价格={bar.close}")
            
            # 根据信号执行交易
            if current_signal == 1 and self.position == 0:
                # 买入信号
                self.log(f"检测到买入信号 价格={bar.close}")
                order_req = OrderRequest(
                    symbol=bar.symbol,
                    side=TradeSide.BUY,
                    quantity=self.parameters.get("quantity", 0.01),
                    price=bar.close,
                    order_type=OrderType.MARKET,
                    strategy_id=self.strategy_id
                )
                res = await self.send_order(order_req)
                logger.info(f"[策略:{self.strategy_id}] 买入订单 {res.status}, 成交数量={res.filled_quantity}")
                if res.status == "FILLED":
                    self.position = res.filled_quantity
                    
            elif current_signal == -1 and self.position > 0:
                # 卖出信号
                self.log(f"检测到卖出信号 价格={bar.close}")
                order_req = OrderRequest(
                    symbol=bar.symbol,
                    side=TradeSide.SELL,
                    quantity=self.position,
                    price=bar.close,
                    order_type=OrderType.MARKET,
                    strategy_id=self.strategy_id
                )
                res = await self.send_order(order_req)
                logger.info(f"[策略:{self.strategy_id}] 卖出订单 {res.status}, 成交数量={res.filled_quantity}")
                if res.status == "FILLED":
                    self.position = 0
                    
        except Exception as e:
            self.log(f"信号生成错误: {e}", "ERROR")
            
    def _get_min_bars_required(self) -> int:
        """返回每种策略类型所需的最小K线数量"""
        min_bars_map = {
            "ma": 60,          # slow_period 默认 30 + 缓冲
            "rsi": 30,          # rsi_period 14 + 缓冲
            "boll": 40,         # period 20 + 缓冲
            "macd": 50,         # slow=26 + 缓冲
            "ema_triple": 100,  # slow_period 60 + 缓冲
            "atr_trend": 50,    # atr_period 14 + trend_period 20
            "turtle": 50,       # entry_period 20 + exit_period 10 + 缓冲
            "ichimoku": 80,     # senkou_b_period 52 + 缓冲
            "smart_beta": 5,    # 仅使用当前数据
            "basis": 5,         # 仅使用当前数据
        }
        return min_bars_map.get(self.strategy_type, 30)

    async def on_tick(self, tick):
        # 可选的Tick级别逻辑
        pass
