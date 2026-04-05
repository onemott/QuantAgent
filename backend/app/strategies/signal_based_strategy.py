"""
基于信号的策略适配器
将 strategy_templates 中的信号函数封装到 BaseStrategy 接口中。
支持所有策略类型：ma, rsi, boll, macd, ema_triple, atr_trend, turtle, ichimoku

注意：smart_beta 和 basis 是需要实时宏观数据的异步策略，
      不适合历史回放。它们已被排除。
"""

import logging
import pandas as pd
import numpy as np
import inspect
from typing import Dict, Any, Optional
from app.core.strategy import BaseStrategy
from app.models.trading import BarData, OrderRequest, TradeSide, OrderType
from app.services.strategy_templates import build_signal_func

logger = logging.getLogger(__name__)

# 需要实时外部数据的异步策略（不适合回测）
ASYNC_STRATEGIES = {"smart_beta", "basis"}


def _safe_int(val, default=0):
    """安全地将值转换为 int，失败时返回 None"""
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _safe_float(val, default=0.0):
    """安全地将值转换为 float，失败时返回 None"""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None

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
        # 信号统计追踪
        self._total_bars_processed = 0
        self._total_buy_signals = 0
        self._total_sell_signals = 0
        self._signal_errors = 0
        
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
            # 使用默认参数，但保留原始 params 中的非策略参数（如 interval）
            default_params = self._get_default_params()
            merged_params = dict(params)  # 复制原始参数
            merged_params.update(default_params)  # 用默认参数覆盖策略特定参数
            params = merged_params
            logger.info(f"[策略:{self.strategy_id}] 参数验证失败，使用默认参数合并非策略参数: {params}")

        # 构建带有固化参数的信号函数
        try:
            logger.info(f"[策略:{self.strategy_id}] 正在构建信号函数: strategy_type={self.strategy_type}, params={params}")
            self._signal_func = build_signal_func(self.strategy_type, params)
            if self._signal_func is not None:
                logger.info(f"[策略:{self.strategy_id}] ✅ 信号函数构建成功: type={type(self._signal_func).__name__}")
            else:
                logger.error(f"[策略:{self.strategy_id}] ❌ 信号函数构建返回 None!")
            # 验证信号函数是否为同步（非异步）
            if inspect.iscoroutinefunction(self._signal_func):
                self.log(f"策略 {self.strategy_type} 是异步的，跳过", "WARNING")
                self._signal_func = None
        except Exception as e:
            import traceback
            self.log(f"构建信号函数失败: {e}\n{traceback.format_exc()}", "ERROR")
            self._signal_func = None

    def _validate_parameters(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        验证策略参数的有效性。
        返回: {"success": bool, "warnings": list}
        """
        warnings = []
        success = True

        if self.strategy_type == "ma":
            fast_period = _safe_int(params.get("fast_period", 10))
            slow_period = _safe_int(params.get("slow_period", 30))
            if fast_period is None:
                warnings.append(f"ma fast_period 必须是有效的整数，当前值: {params.get('fast_period')}")
                success = False
            elif fast_period <= 0:
                warnings.append(f"ma fast_period 必须 > 0，当前值: {fast_period}")
                success = False
            if slow_period is None:
                warnings.append(f"ma slow_period 必须是有效的整数，当前值: {params.get('slow_period')}")
                success = False
            elif slow_period <= 0:
                warnings.append(f"ma slow_period 必须 > 0，当前值: {slow_period}")
                success = False
            elif fast_period is not None and slow_period <= fast_period:
                warnings.append(f"ma slow_period ({slow_period}) 必须 > fast_period ({fast_period})")
                success = False

        elif self.strategy_type == "rsi":
            rsi_period = _safe_int(params.get("rsi_period", 14))
            oversold = _safe_float(params.get("oversold", 30.0))
            overbought = _safe_float(params.get("overbought", 70.0))
            if rsi_period is None:
                warnings.append(f"rsi rsi_period 必须是有效的整数，当前值: {params.get('rsi_period')}")
                success = False
            elif rsi_period <= 0:
                warnings.append(f"rsi rsi_period 必须 > 0，当前值: {rsi_period}")
                success = False
            if oversold is None:
                warnings.append(f"rsi oversold 必须是有效的数值，当前值: {params.get('oversold')}")
                success = False
            if overbought is None:
                warnings.append(f"rsi overbought 必须是有效的数值，当前值: {params.get('overbought')}")
                success = False
            if oversold is not None and overbought is not None and overbought <= oversold:
                warnings.append(f"rsi overbought ({overbought}) 必须 > oversold ({oversold})")
                success = False

        elif self.strategy_type == "boll":
            period = _safe_int(params.get("period", 20))
            std_dev = _safe_float(params.get("std_dev", 2.0))
            if period is None:
                warnings.append(f"boll period 必须是有效的整数，当前值: {params.get('period')}")
                success = False
            elif period <= 0:
                warnings.append(f"boll period 必须 > 0，当前值: {period}")
                success = False
            if std_dev is None:
                warnings.append(f"boll std_dev 必须是有效的数值，当前值: {params.get('std_dev')}")
                success = False
            elif std_dev <= 0:
                warnings.append(f"boll std_dev 必须 > 0，当前值: {std_dev}")
                success = False

        elif self.strategy_type == "macd":
            fast = _safe_int(params.get("fast", 12))
            slow = _safe_int(params.get("slow", 26))
            signal_period = _safe_int(params.get("signal_period", 9))
            if fast is None:
                warnings.append(f"macd fast 必须是有效的整数，当前值: {params.get('fast')}")
                success = False
            elif fast <= 0:
                warnings.append(f"macd fast 必须 > 0，当前值: {fast}")
                success = False
            if slow is None:
                warnings.append(f"macd slow 必须是有效的整数，当前值: {params.get('slow')}")
                success = False
            elif fast is not None and slow <= fast:
                warnings.append(f"macd slow ({slow}) 必须 > fast ({fast})")
                success = False
            if signal_period is None:
                warnings.append(f"macd signal_period 必须是有效的整数，当前值: {params.get('signal_period')}")
                success = False
            elif signal_period <= 0:
                warnings.append(f"macd signal_period 必须 > 0，当前值: {signal_period}")
                success = False

        elif self.strategy_type == "ema_triple":
            fast_period = _safe_int(params.get("fast_period", 5))
            mid_period = _safe_int(params.get("mid_period", 20))
            slow_period = _safe_int(params.get("slow_period", 60))
            if fast_period is None:
                warnings.append(f"ema_triple fast_period 必须是有效的整数，当前值: {params.get('fast_period')}")
                success = False
            elif fast_period <= 0:
                warnings.append(f"ema_triple fast_period 必须 > 0，当前值: {fast_period}")
                success = False
            if mid_period is None:
                warnings.append(f"ema_triple mid_period 必须是有效的整数，当前值: {params.get('mid_period')}")
                success = False
            elif fast_period is not None and mid_period <= fast_period:
                warnings.append(f"ema_triple mid_period ({mid_period}) 必须 > fast_period ({fast_period})")
                success = False
            if slow_period is None:
                warnings.append(f"ema_triple slow_period 必须是有效的整数，当前值: {params.get('slow_period')}")
                success = False
            elif mid_period is not None and slow_period <= mid_period:
                warnings.append(f"ema_triple slow_period ({slow_period}) 必须 > mid_period ({mid_period})")
                success = False

        elif self.strategy_type == "atr_trend":
            atr_period = _safe_int(params.get("atr_period", 14))
            atr_multiplier = _safe_float(params.get("atr_multiplier", 2.0))
            trend_period = _safe_int(params.get("trend_period", 20))
            if atr_period is None:
                warnings.append(f"atr_trend atr_period 必须是有效的整数，当前值: {params.get('atr_period')}")
                success = False
            elif atr_period <= 0:
                warnings.append(f"atr_trend atr_period 必须 > 0，当前值: {atr_period}")
                success = False
            if atr_multiplier is None:
                warnings.append(f"atr_trend atr_multiplier 必须是有效的数值，当前值: {params.get('atr_multiplier')}")
                success = False
            elif atr_multiplier <= 0:
                warnings.append(f"atr_trend atr_multiplier 必须 > 0，当前值: {atr_multiplier}")
                success = False
            if trend_period is None:
                warnings.append(f"atr_trend trend_period 必须是有效的整数，当前值: {params.get('trend_period')}")
                success = False
            elif trend_period <= 0:
                warnings.append(f"atr_trend trend_period 必须 > 0，当前值: {trend_period}")
                success = False

        elif self.strategy_type == "turtle":
            entry_period = _safe_int(params.get("entry_period", 20))
            exit_period = _safe_int(params.get("exit_period", 10))
            if entry_period is None:
                warnings.append(f"turtle entry_period 必须是有效的整数，当前值: {params.get('entry_period')}")
                success = False
            elif entry_period <= 0:
                warnings.append(f"turtle entry_period 必须 > 0，当前值: {entry_period}")
                success = False
            if exit_period is None:
                warnings.append(f"turtle exit_period 必须是有效的整数，当前值: {params.get('exit_period')}")
                success = False
            elif exit_period <= 0:
                warnings.append(f"turtle exit_period 必须 > 0，当前值: {exit_period}")
                success = False

        elif self.strategy_type == "ichimoku":
            tenkan_period = _safe_int(params.get("tenkan_period", 9))
            kijun_period = _safe_int(params.get("kijun_period", 26))
            senkou_b_period = _safe_int(params.get("senkou_b_period", 52))
            if tenkan_period is None:
                warnings.append(f"ichimoku tenkan_period 必须是有效的整数，当前值: {params.get('tenkan_period')}")
                success = False
            elif tenkan_period <= 0:
                warnings.append(f"ichimoku tenkan_period 必须 > 0，当前值: {tenkan_period}")
                success = False
            if kijun_period is None:
                warnings.append(f"ichimoku kijun_period 必须是有效的整数，当前值: {params.get('kijun_period')}")
                success = False
            elif tenkan_period is not None and kijun_period <= tenkan_period:
                warnings.append(f"ichimoku kijun_period ({kijun_period}) 必须 > tenkan_period ({tenkan_period})")
                success = False
            if senkou_b_period is None:
                warnings.append(f"ichimoku senkou_b_period 必须是有效的整数，当前值: {params.get('senkou_b_period')}")
                success = False
            elif kijun_period is not None and senkou_b_period <= kijun_period:
                warnings.append(f"ichimoku senkou_b_period ({senkou_b_period}) 必须 > kijun_period ({kijun_period})")
                success = False

        else:
            # 未知策略类型警告
            if self.strategy_type not in ASYNC_STRATEGIES:
                warnings.append(f"未知策略类型: {self.strategy_type}，参数验证已跳过")
                logger.warning(f"[策略:{self.strategy_id}] 未知策略类型: {self.strategy_type}")

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
            if isinstance(val, float) and (pd.isna(val) or np.isinf(val)):
                return False
        return True

    async def on_bar(self, bar: BarData):
        # 检查bar数据完整性
        if not self._is_valid_bar(bar):
            logger.warning(f"[策略:{self.strategy_id}] 收到无效bar数据，跳过处理")
            return
    
        self.bars.append(bar)
    
        # 保留足够的K线数据（有状态策略需要更长历史来维护 in_position）
        max_bars_map = {
            "ma": 200,
            "rsi": 200,
            "boll": 200,
            "macd": 200,
            "ema_triple": 500,   # EMA 需要更长历史保证精度
            "atr_trend": 500,   # 有状态策略，需要更长历史来维护 in_position
            "turtle": 500,       # 有状态策略
            "ichimoku": 500,     # 有状态策略
        }
        max_period = max_bars_map.get(self.strategy_type, 200)
        if len(self.bars) > max_period:
            self.bars.pop(0)
    
        # 指标计算需要最小K线数量
        min_bars = self._get_min_bars_required()
        if len(self.bars) < min_bars:
            if len(self.bars) % 50 == 0:
                logger.debug(f"[策略:{self.strategy_id}] K线数量不足: {len(self.bars)}/{min_bars}")
            return
    
        # 首次达到最小K线阈值时记录一次
        if len(self.bars) == min_bars:
            logger.info(f"[策略:{self.strategy_id}] 已达到最小K线数量 ({min_bars})，开始生成信号")
            logger.info(f"[策略:{self.strategy_id}] 信号函数状态: {self._signal_func is not None}")
            if self._signal_func:
                logger.info(f"[策略:{self.strategy_id}] 信号函数类型: {type(self._signal_func)}")
    
        # 生成信号
        if self._signal_func is None:
            if self._total_bars_processed == 0:
                logger.error(f"[策略:{self.strategy_id}] 信号函数未初始化，strategy_type={self.strategy_type}，所有信号将丢失！")
            return

        self._total_bars_processed += 1

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
            
            # 确保timestamp是datetime类型并设为索引
            if not pd.api.types.is_datetime64_any_dtype(df['timestamp']):
                df['timestamp'] = pd.to_datetime(df['timestamp'])
            df.set_index('timestamp', inplace=True)
            
            # 生成信号
            signal = self._signal_func(df)
            
            if signal is None or len(signal) == 0:
                logger.debug(f"[策略:{self.strategy_id}] 信号为空")
                return
                
            current_signal = signal.iloc[-1]
            
            # 统计信号
            if current_signal == 1:
                self._total_buy_signals += 1
            elif current_signal == -1:
                self._total_sell_signals += 1
            
            # 每 500 根K线输出信号统计
            if self._total_bars_processed % 500 == 0:
                window_buy = (signal == 1).sum()
                window_sell = (signal == -1).sum()
                logger.info(
                    f"[策略:{self.strategy_id}] 📊 信号统计 (已处理 {self._total_bars_processed} 根K线): "
                    f"累计买入信号={self._total_buy_signals}, 累计卖出信号={self._total_sell_signals}, "
                    f"当前窗口信号(买/卖)={window_buy}/{window_sell}, "
                    f"当前持仓={self.position}, bars窗口={len(valid_bars)}, "
                    f"信号错误数={self._signal_errors}"
                )
            
            # 信号状态与实际持仓状态同步检查
            # 防止窗口滚动导致信号函数的 in_position 状态与策略 self.position 不同步
            if self.position > 0 and current_signal == 1:
                # 已有持仓但信号函数认为没有持仓（因窗口截断导致状态丢失）
                # 忽略这个错误的买入信号
                logger.debug(f"[策略:{self.strategy_id}] 忽略买入信号：已有持仓 ({self.position})，信号状态可能因窗口滚动不同步")
                return

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
                commission_rate = 0.001   # 与 paper_trading_service FEE_RATE 对齐
                slippage_pct = 0.0005     # 与 paper_trading_service SLIPPAGE_PCT 对齐
                effective_price = bar.close * (1 + slippage_pct)
                
                # 默认使用初始资金进行仓位计算，避免利润复利导致仓位过大或资金异常时仓位失控
                initial_capital = self.parameters.get("initial_capital", available_capital)
                # 确保下单使用的资金不超过当前可用资金
                use_capital = min(initial_capital, available_capital)
                
                quantity = use_capital / (effective_price * (1 + commission_rate))

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
            self._signal_errors += 1
            import traceback
            self.log(
                f"信号生成错误: {type(e).__name__}: {e}\n"
                f"  bars数量={len(self.bars)}, strategy_type={self.strategy_type}, "
                f"参数={self.params if hasattr(self, 'params') else 'N/A'}\n"
                f"  累计错误数={self._signal_errors}\n"
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
