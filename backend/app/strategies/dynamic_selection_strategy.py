import logging
from typing import Dict, Any, List
from datetime import datetime, timezone

from app.core.strategy import BaseStrategy
from app.core.virtual_bus import VirtualTradingBus
from app.models.trading import BarData, TickData, OrderRequest, TradeSide, OrderType
from app.models.db_models import SelectionHistory

from app.services.dynamic_selection.evaluator import StrategyEvaluator
from app.services.dynamic_selection.ranker import StrategyRanker
from app.services.dynamic_selection.eliminator import StrategyEliminator, EliminationRule
from app.services.dynamic_selection.weight_allocator import WeightAllocator
from app.strategies.composition.weighted import WeightedComposer
from app.services.database import get_session_factory

from app.strategies.signal_based_strategy import SignalBasedStrategy
from app.strategies.ma_cross import MaCrossStrategy

logger = logging.getLogger(__name__)

class DynamicSelectionStrategy(BaseStrategy):
    """
    Dynamic Selection Strategy
    
    A composite strategy that manages multiple atomic strategies internally.
    It periodically evaluates their performance, eliminates the underperforming ones,
    and reallocates weights to the surviving ones.
    The final trading signal is a weighted combination of the atomic strategies' signals.
    """
    
    def __init__(self, strategy_id: str, bus: 'TradingBus'):
        super().__init__(strategy_id, bus)
        
        self.alive_strategies: Dict[str, BaseStrategy] = {}
        self.virtual_buses: Dict[str, VirtualTradingBus] = {}
        
        self.consecutive_low_counts: Dict[str, int] = {}
        self.last_evaluation_bar_index = 0
        self._last_evaluation_datetime: datetime = None  # 记录上次评估时间
        self.current_position = 0.0
        self.bar_count = 0
        
        self.composer = None
        self.evaluator = StrategyEvaluator()
        self.ranker = StrategyRanker()
        self.eliminator = StrategyEliminator()
        self.weight_allocator = WeightAllocator()
        
        self.evaluation_period = 1440
        self.weight_method = "score_based"
        self.elimination_rule = EliminationRule()

    def set_parameters(self, params: Dict[str, Any]):
        """
        Initialize the dynamic selection strategy parameters and atomic strategies.
        """
        super().set_parameters(params)
        
        atomic_strategies = params.get("atomic_strategies", [])
        if not atomic_strategies:
            logger.warning(f"[{self.strategy_id}] No atomic_strategies provided.")
            threshold = params.get("composition_threshold", 0.5)
            self.composer = WeightedComposer(
                composition_id="dynamic_weighted", weights={}, threshold=threshold
            )
            return
            
        num_strategies = len(atomic_strategies)
        total_capital = params.get("initial_capital", 10000.0)
        per_capital = params.get("per_strategy_capital", total_capital / num_strategies)

        expected_symbol = None

        for item in atomic_strategies:
            item_id = item.get("strategy_id")
            strategy_type = item.get("strategy_type")

            item_symbol = item.get("params", {}).get("symbol") or item.get("symbol")
            if item_symbol:
                if expected_symbol is None:
                    expected_symbol = item_symbol
                elif item_symbol != expected_symbol:
                    logger.warning(f"[{self.strategy_id}] Symbol mismatch in atomic_strategies: '{item_symbol}' differs from expected '{expected_symbol}'. Forcing to '{expected_symbol}'.")

            if not item_id or not strategy_type:
                logger.error(f"[{self.strategy_id}] Invalid atomic strategy config: {item}")
                continue
                
            vbus = VirtualTradingBus(initial_capital=per_capital)
            
            if strategy_type in ["ma", "rsi", "boll", "macd", "ema_triple", "atr_trend", "turtle", "ichimoku"]:
                strategy = SignalBasedStrategy(strategy_id=item_id, bus=vbus, strategy_type=strategy_type)
            elif strategy_type == "ma_cross":
                strategy = MaCrossStrategy(strategy_id=item_id, bus=vbus)
            else:
                logger.error(f"[{self.strategy_id}] Unsupported strategy_type: {strategy_type}")
                continue
                
            strategy.set_parameters(item.get("params", {}))
            
            self.virtual_buses[item_id] = vbus
            self.alive_strategies[item_id] = strategy
            self.consecutive_low_counts[item_id] = 0
            
        # 防御性检查：确保有策略被成功注册
        if not self.alive_strategies:
            logger.warning(f"[{self.strategy_id}] No atomic strategies were successfully registered. "
                           f"All {num_strategies} strategies were skipped due to invalid config or unsupported type.")
            self.composer = WeightedComposer(composition_id="dynamic_weighted", weights={}, threshold=0.5)
            return
        
        # 使用实际存活的策略数量计算初始权重，确保权重总和等于 1.0
        alive_count = len(self.alive_strategies)
        if alive_count < num_strategies:
            logger.info(f"[{self.strategy_id}] {num_strategies - alive_count} strategies were skipped. "
                        f"Using {alive_count} strategies for initial weight calculation.")
        
        threshold = params.get("composition_threshold", 0.5)
        initial_weights = {s_id: 1.0 / alive_count for s_id in self.alive_strategies.keys()}
        self.composer = WeightedComposer(composition_id="dynamic_weighted", weights=initial_weights, threshold=threshold)
        
        rule_params = params.get("elimination_rule", {})
        self.elimination_rule = EliminationRule(**rule_params)
        
        self.evaluation_period = params.get("evaluation_period", 1440)
        self.weight_method = params.get("weight_method", "score_based")
        
    async def on_tick(self, tick: TickData):
        pass
        
    async def on_bar(self, bar: BarData):
        self.bar_count += 1
        
        # 1. Update virtual buses and execute atomic strategies
        for s_id, strategy in list(self.alive_strategies.items()):
            vbus = self.virtual_buses[s_id]
            await vbus.publish_bar(bar)
            await strategy.on_bar(bar)
            
        # 2. Check if we need to evaluate and eliminate
        if self.bar_count - self.last_evaluation_bar_index >= self.evaluation_period:
            await self._run_evaluation(bar)
            
        # 3. Compose signal and execute
        signal = self._compose_signal()
        await self._execute_signal(signal, bar)
        
    async def _run_evaluation(self, bar: BarData):
        if not self.alive_strategies:
            return
            
        # 计算评估窗口：从上次评估时间到当前时间
        window_start = self._last_evaluation_datetime if self._last_evaluation_datetime else bar.datetime
        window_end = bar.datetime
        
        evaluations = []
        for s_id, strategy in self.alive_strategies.items():
            vbus = self.virtual_buses[s_id]
            performance = vbus.get_performance_metric()
            eval_obj = self.evaluator.evaluate(
                strategy_id=s_id,
                performance=performance,
                window_start=window_start,
                window_end=window_end,
                evaluation_date=bar.datetime
            )
            evaluations.append(eval_obj)
            
        ranked_strategies = self.ranker.rank_evaluations(evaluations)
        surviving, eliminated, reasons = self.eliminator.apply_elimination(
            ranked_strategies, 
            self.elimination_rule, 
            self.consecutive_low_counts
        )
        
        for rs in surviving:
            if rs.score < self.elimination_rule.low_score_threshold:
                self.consecutive_low_counts[rs.strategy_id] += 1
            else:
                self.consecutive_low_counts[rs.strategy_id] = 0
                
        eliminated_ids = [rs.strategy_id for rs in eliminated]
        for e_id in eliminated_ids:
            if e_id in self.alive_strategies:
                del self.alive_strategies[e_id]
            if e_id in self.virtual_buses:
                del self.virtual_buses[e_id]
            if e_id in self.consecutive_low_counts:
                del self.consecutive_low_counts[e_id]
                
        new_weights = self.weight_allocator.allocate_weights(surviving, method=self.weight_method)
        self.composer.update_weights(new_weights)
        
        # Save to DB
        session_id = getattr(self.bus, "session_id", None)
        history = SelectionHistory(
            session_id=session_id,
            evaluation_date=bar.datetime,
            total_strategies=len(ranked_strategies),
            surviving_count=len(surviving),
            eliminated_count=len(eliminated),
            eliminated_strategy_ids=eliminated_ids,
            elimination_reasons=reasons,
            strategy_weights=new_weights
        )
        
        factory = get_session_factory()
        try:
            async with factory() as db_session:
                db_session.add(history)
                await db_session.commit()
        except Exception as e:
            logger.error(f"[{self.strategy_id}] Failed to save SelectionHistory: {e}")
        
        # 更新上次评估时间
        self._last_evaluation_datetime = bar.datetime
        self.last_evaluation_bar_index = self.bar_count
        
    def _compose_signal(self) -> int:
        if not self.alive_strategies:
            return 0
            
        weighted_sum = 0.0
        total_weight = 0.0
        
        for s_id in self.alive_strategies.keys():
            vbus = self.virtual_buses[s_id]
            position = vbus.router.position
            
            signal = 0
            if position > 0:
                signal = 1
            elif position < 0:
                signal = -1
                
            weight = self.composer.weights.get(s_id, 0.0)
            weighted_sum += signal * weight
            total_weight += abs(weight)
            
        if total_weight > 0:
            weighted_sum /= total_weight
            
        if weighted_sum >= self.composer.threshold:
            return 1
        elif weighted_sum <= -self.composer.threshold:
            return -1
        else:
            return 0
            
    async def _execute_signal(self, signal: int, bar: BarData):
        if self.current_position == 0 and signal == 1:
            balance_info = await self.bus.get_balance()
            available_capital = balance_info.get("available_balance", 0.0)
            
            if available_capital <= 0 or bar.close <= 0:
                return
                
            commission_rate = 0.001
            slippage_pct = 0.0005
            effective_price = bar.close * (1 + slippage_pct)
            
            initial_capital = self.parameters.get("initial_capital", available_capital)
            use_capital = min(initial_capital, available_capital)
            
            quantity = use_capital / (effective_price * (1 + commission_rate))
            if quantity > 0:
                order_req = OrderRequest(
                    symbol=bar.symbol,
                    side=TradeSide.BUY,
                    quantity=quantity,
                    price=bar.close,
                    order_type=OrderType.MARKET,
                    strategy_id=self.strategy_id
                )
                res = await self.send_order(order_req)
                if res.status == "FILLED":
                    self.current_position = res.filled_quantity
                    
        elif self.current_position > 0 and signal <= 0:
            order_req = OrderRequest(
                symbol=bar.symbol,
                side=TradeSide.SELL,
                quantity=self.current_position,
                price=bar.close,
                order_type=OrderType.MARKET,
                strategy_id=self.strategy_id
            )
            res = await self.send_order(order_req)
            if res.status == "FILLED":
                self.current_position = 0.0
