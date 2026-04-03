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
        """设置策略参数，包含参数验证逻辑。"""
        # None 检查
        if params is None:
            params = {}
            logger.warning(f"[策略:{self.strategy_id}] 参数为 None，使用空字典")

        super().set_parameters(params)

        # 跳过异步策略（需要实时数据）
        if self.strategy_type in ASYNC_STRATEGIES:
            self.log(f"跳过异步策略: {self.strategy_type}", "WARNING")
            self._signal_func = None
            return

        # 验证参数
        validation_result = self._validate_parameters(params)
        if not validation_result["success"]:
            for warning in validation_result["warnings"]:
                logger.warning(f"[策略:{self.strategy_id}] {warning}")
            # 使用默认参数
            params = self._get_default_params()
            logger.info(f"[策略:{self.strategy_id}] 使用默认参数: {params}")

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

    def _validate_parameters(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        验证策略参数的有效性。
        返回: {"success": bool, "warnings": list}
        """
        warnings = []
        success = True

        if self.strategy_type == "ma":
            fast_period = params.get("fast_period", 10)
            slow_period = params.get("slow_period", 30)
            if fast_period <= 0:
                warnings.append(f"ma fast_period 必须 > 0，当前值: {fast_period}")
                success = False
            if slow_period <= fast_period:
                warnings.append(f"ma slow_period ({slow_period}) 必须 > fast_period ({fast_period})")
                success = False

        elif self.strategy_type == "rsi":
            rsi_period = params.get("rsi_period", 14)
            oversold = params.get("oversold", 30.0)
            overbought = params.get("overbought", 70.0)
            if rsi_period <= 0:
                warnings.append(f"rsi rsi_period 必须 > 0，当前值: {rsi_period}")
                success = False
            if overbought <= oversold:
                warnings.append(f"rsi overbought ({overbought}) 必须 > oversold ({oversold})")
                success = False

        elif self.strategy_type == "boll":
            period = params.get("period", 20)
            std_dev = params.get("std_dev", 2.0)
            if period <= 0:
                warnings.append(f"boll period 必须 > 0，当前值: {period}")
                success = False
            if std_dev <= 0:
                warnings.append(f"boll std_dev 必须 > 0，当前值: {std_dev}")
                success = False

        elif self.strategy_type == "macd":
            fast = params.get("fast", 12)
            slow = params.get("slow", 26)
            signal_period = params.get("signal_period", 9)
            if fast <= 0:
                warnings.append(f"macd fast 必须 > 0，当前值: {fast}")
                success = False
            if slow <= fast:
                warnings.append(f"macd slow ({slow}) 必须 > fast ({fast})")
                success = False
            if signal_period <= 0:
                warnings.append(f"macd signal_period 必须 > 0，当前值: {signal_period}")
                success = False

        elif self.strategy_type == "ema_triple":
            fast_period = params.get("fast_period", 5)
            mid_period = params.get("mid_period", 20)
            slow_period = params.get("slow_period", 60)
            if fast_period <= 0:
                warnings.append(f"ema_triple fast_period 必须 > 0，当前值: {fast_period}")
                success = False
            if mid_period <= fast_period:
                warnings.append(f"ema_triple mid_period ({mid_period}) 必须 > fast_period ({fast_period})")
                success = False
            if slow_period <= mid_period:
                warnings.append(f"ema_triple slow_period ({slow_period}) 必须 > mid_period ({mid_period})")
                success = False

        elif self.strategy_type == "atr_trend":
            atr_period = params.get("atr_period", 14)
            atr_multiplier = params.get("atr_multiplier", 2.0)
            trend_period = params.get("trend_period", 20)
            if atr_period <= 0:
                warnings.append(f"atr_trend atr_period 必须 > 0，当前值: {atr_period}")
                success = False
            if atr_multiplier <= 0:
                warnings.append(f"atr_trend atr_multiplier 必须 > 0，当前值: {atr_multiplier}")
                success = False
            if trend_period <= 0:
                warnings.append(f"atr_trend trend_period 必须 > 0，当前值: {trend_period}")
                success = False

        elif self.strategy_type == "turtle":
            entry_period = params.get("entry_period", 20)
            exit_period = params.get("exit_period", 10)
            if entry_period <= 0:
                warnings.append(f"turtle entry_period 必须 > 0，当前值: {entry_period}")
                success = False
            if exit_period <= 0:
                warnings.append(f"turtle exit_period 必须 > 0，当前值: {exit_period}")
                success = False

        elif self.strategy_type == "ichimoku":
            tenkan_period = params.get("tenkan_period", 9)
            kijun_period = params.get("kijun_period", 26)
            senkou_b_period = params.get("senkou_b_period", 52)
            if tenkan_period <= 0:
                warnings.append(f"ichimoku tenkan_period 必须 > 0，当前值: {tenkan_period}")
                success = False
            if kijun_period <= tenkan_period:
                warnings.append(f"ichimoku kijun_period ({kijun_period}) 必须 > tenkan_period ({tenkan_period})")
                success = False
            if senkou_b_period <= kijun_period:
                warnings.append(f"ichimoku senkou_b_period ({senkou_b_period}) 必须 > kijun_period ({kijun_period})")
                success = False

        return {"success": success, "warnings": warnings}

    def _get_default_params(self) -> Dict[str, Any]:
        """获取策略的默认参数。"""
        default_params_map = {
            "ma": {"fast_period": 10, "slow_period": 30},
            "rsi": {"rsi_period": 14, "oversold": 30.0, "overbought": 70.0},
            "boll": {"period": 20, "std_dev": 2.0},
            "macd": {"fast": 12, "slow": 26, "signal_period": 9},
            "ema_triple": {"fast_period": 5, "mid_period": 20, "slow_period": 60},
            "atr_trend": {"atr_period": 14, "atr_multiplier": 2.0, "trend_period": 20},
            "turtle": {"entry_period": 20, "exit_period": 10},
            "ichimoku": {"tenkan_period": 9, "kijun_period": 26, "senkou_b_period": 52},
        }
        return default_params_map.get(self.strategy_type, {})

    def _is_valid_bar(self, bar: BarData) -> bool:
        """检查 bar 数据完整性（open/high/low/close 非 None、非 NaN）。"""
        if bar is None:
            return False
        required_fields = ['open', 'high', 'low', 'close']
        for field in required_fields:
            val = getattr(bar, field, None)
            if val is None:
                return False
            if isinstance(val, float) and (pd.isna(val) or pd.isinf(val)):
                return False
        return True

    async def on_bar(self, bar: BarData):
        # 检查 bar 数据完整性
        if not self._is_valid_bar(bar):
            logger.warning(f"[策略:{self.strategy_id}] 收到无效 bar 数据，跳过处理")
            return

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
            # 过滤无效 bar
            valid_bars = [b for b in self.bars if self._is_valid_bar(b)]
            if len(valid_bars) < min_bars:
                logger.warning(f"[策略:{self.strategy_id}] 有效 bar 数量不足 ({len(valid_bars)}/{min_bars})，跳过信号生成")
                return

            df = pd.DataFrame([{
                'timestamp': b.datetime,
                'open': b.open,
                'high': b.high,
                'low': b.low,
                'close': b.close,
                'volume': getattr(b, 'volume', 0)
            } for b in valid_bars])
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
                # 买入信号 - 全仓模式（与回测引擎对齐）
                self.log(f"检测到买入信号 价格={bar.close}")

                # 获取当前可用资金
                balance_info = await self.bus.get_balance()
                available_capital = balance_info.get("available_balance", 0)

                # 防御性检查
                if available_capital <= 0:
                    logger.warning(f"[策略:{self.strategy_id}] 可用资金不足，跳过买入 (available={available_capital})")
                    return
                if bar.close <= 0:
                    logger.warning(f"[策略:{self.strategy_id}] 无效价格，跳过买入 (price={bar.close})")
                    return

                # 使用与撮合侧一致的手续费和滑点参数反推全仓数量
                # 撮合侧：fee = qty * effective_price * FEE_RATE, effective_price = price * (1 + SLIPPAGE_PCT)
                # 全仓条件：available_capital = qty * effective_price * (1 + FEE_RATE)
                # 解出：qty = available_capital / (effective_price * (1 + FEE_RATE))
                commission_rate = 0.001   # 与 paper_trading_service FEE_RATE 对齐
                slippage_pct = 0.0005     # 与 paper_trading_service SLIPPAGE_PCT 对齐
                effective_price = bar.close * (1 + slippage_pct)
                quantity = available_capital / (effective_price * (1 + commission_rate))

                if quantity <= 0:
                    logger.warning(f"[策略:{self.strategy_id}] 计算买入数量非正，跳过 (quantity={quantity})")
                    return

                order_req = OrderRequest(
                    symbol=bar.symbol,
                    side=TradeSide.BUY,
                    quantity=quantity,
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
            import traceback
            self.log(
                f"信号生成错误: {type(e).__name__}: {e}\n"
                f"  bars数量={len(self.bars)}, strategy_type={self.strategy_type}, "
                f"参数={self.params if hasattr(self, 'params') else 'N/A'}\n"
                f"  traceback:\n{traceback.format_exc()}",
                "ERROR"
            )
            
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
