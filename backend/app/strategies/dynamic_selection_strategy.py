import logging
from typing import Dict, Any, List
from datetime import datetime, timezone

from app.core.strategy import BaseStrategy
from app.core.virtual_bus import VirtualTradingBus
from app.models.trading import BarData, TickData, OrderRequest, TradeSide, OrderType
from app.models.db_models import SelectionHistory

from app.services.dynamic_selection.evaluator import StrategyEvaluator
from app.services.dynamic_selection.ranker import StrategyRanker
from app.services.dynamic_selection.eliminator import StrategyEliminator, EliminationRule, RevivalRule
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

        # 休眠策略状态管理
        self.hibernating_strategies: Dict[str, Any] = {}  # 休眠策略集合
        self.hibernating_buses: Dict[str, Any] = {}  # 休眠策略的虚拟总线
        self.consecutive_high_counts: Dict[str, int] = {}  # 休眠策略连续高分计数

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
        self.revival_rule = RevivalRule()
        
        # 缓存 session_id，避免每次评估时重新获取
        self._cached_session_id: str = None
        self._session_id_logged = False  # 避免重复日志
        self._initial_evaluation_done = False  # 追踪是否已完成初始评估

    def set_parameters(self, params: Dict[str, Any]):
        """
        Initialize the dynamic selection strategy parameters and atomic strategies.
        """
        super().set_parameters(params)
        
        # 缓存 session_id 并记录日志
        self._cached_session_id = getattr(self.bus, "session_id", None)
        if self._cached_session_id:
            logger.info(f"[{self.strategy_id}] Session ID cached: {self._cached_session_id}")
        else:
            logger.warning(f"[{self.strategy_id}] session_id is None! SelectionHistory records will have NULL session_id. "
                           f"Bus type: {type(self.bus).__name__}. Check if bus.session_id is properly initialized.")
        
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
        
        elimination_rule_params = params.get("elimination_rule", {})
        if elimination_rule_params:
            self.elimination_rule = EliminationRule(**elimination_rule_params)
        
        revival_rule_params = params.get("revival_rule", {})
        if revival_rule_params:
            self.revival_rule = RevivalRule(
                revival_score_threshold=float(revival_rule_params.get("revival_score_threshold", 45.0)),
                min_consecutive_high=int(revival_rule_params.get("min_consecutive_high", 2)),
                max_revival_per_round=int(revival_rule_params.get("max_revival_per_round", 2))
            )
        
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
        
        # 休眠策略也继续接收K线数据进行虚拟交易（不产生实际信号）
        for strategy_id, strategy in self.hibernating_strategies.items():
            try:
                bus = self.hibernating_buses.get(strategy_id)
                if bus:
                    await bus.publish_bar(bar)
                    await strategy.on_bar(bar)
            except Exception as e:
                logger.warning(f"Hibernating strategy {strategy_id} on_bar error: {e}")
        
        # 2. 初始评估：确保短期回放也能触发至少一次评估
        #    当达到 evaluation_period 的 10% 时触发初始评估（最少 10 根 K 线）
        if not self._initial_evaluation_done:
            initial_trigger_threshold = max(10, int(self.evaluation_period * 0.1))
            if self.bar_count >= initial_trigger_threshold:
                logger.info(f"[{self.strategy_id}] Triggering initial evaluation at bar {self.bar_count} "
                            f"(threshold: {initial_trigger_threshold}, evaluation_period: {self.evaluation_period})")
                await self._run_evaluation(bar, is_initial=True)
                self._initial_evaluation_done = True
        
        # 3. 定期评估
        if self.bar_count - self.last_evaluation_bar_index >= self.evaluation_period:
            await self._run_evaluation(bar)
            
        # 4. Compose signal and execute
        signal = self._compose_signal()
        await self._execute_signal(signal, bar)
        
    async def _run_evaluation(self, bar: BarData, is_initial: bool = False):
        if not self.alive_strategies:
            return
        
        # 初始化复活相关变量（即使没有休眠策略也要定义）
        revived_ids = []
        revival_reasons = {}
        
        eval_type = "initial" if is_initial else "periodic"
        logger.info(f"[{self.strategy_id}] Running {eval_type} evaluation at {bar.datetime}, "
                    f"bar_count={self.bar_count}, alive_strategies={len(self.alive_strategies)}, "
                    f"session_id={self._cached_session_id}")
            
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
            # 移入休眠而非删除
            if e_id in self.alive_strategies:
                self.hibernating_strategies[e_id] = self.alive_strategies.pop(e_id)
            if e_id in self.virtual_buses:
                self.hibernating_buses[e_id] = self.virtual_buses.pop(e_id)
            # 保留 consecutive_low_counts 记录，初始化连续高分计数
            self.consecutive_high_counts[e_id] = 0
        
        # === 休眠策略虚拟评估与复活检查 ===
        if self.hibernating_strategies:
            # 对休眠策略进行虚拟评估
            hibernating_scores = {}
            for h_id in list(self.hibernating_strategies.keys()):
                try:
                    h_bus = self.hibernating_buses.get(h_id)
                    if h_bus:
                        h_perf = h_bus.get_performance_metric()
                        h_eval = self.evaluator.evaluate(
                            strategy_id=h_id,
                            performance=h_perf,
                            window_start=window_start,
                            window_end=window_end,
                            evaluation_date=bar.datetime
                        )
                        hibernating_scores[h_id] = h_eval.total_score
                except Exception as e:
                    logger.warning(f"Hibernating strategy {h_id} evaluation error: {e}")
            
            # 检查复活条件
            if hibernating_scores:
                revived_ids, self.consecutive_high_counts, revival_reasons = (
                    StrategyEliminator.check_revival(
                        hibernating_scores=hibernating_scores,
                        consecutive_high_counts=self.consecutive_high_counts,
                        rule=self.revival_rule
                    )
                )
                
                # 执行复活：从休眠集合移回活跃集合
                for r_id in revived_ids:
                    if r_id in self.hibernating_strategies:
                        self.alive_strategies[r_id] = self.hibernating_strategies.pop(r_id)
                    if r_id in self.hibernating_buses:
                        self.virtual_buses[r_id] = self.hibernating_buses.pop(r_id)
                    # 重置连续低分计数
                    self.consecutive_low_counts[r_id] = 0
                    # 清除连续高分计数
                    if r_id in self.consecutive_high_counts:
                        del self.consecutive_high_counts[r_id]
                    logger.info(f"Strategy {r_id} revived: {revival_reasons.get(r_id, 'unknown')}")
                
        new_weights = self.weight_allocator.allocate_weights(surviving, method=self.weight_method)
        self.composer.update_weights(new_weights)
        
        # Save to DB - 使用缓存的 session_id
        history = SelectionHistory(
            session_id=self._cached_session_id,
            evaluation_date=bar.datetime,
            total_strategies=len(ranked_strategies),
            surviving_count=len(surviving),
            eliminated_count=len(eliminated),
            eliminated_strategy_ids=eliminated_ids,
            elimination_reasons=reasons,
            strategy_weights=new_weights,
            hibernating_strategy_ids=list(self.hibernating_strategies.keys()),
            revived_strategy_ids=revived_ids,
            revival_reasons=revival_reasons
        )
        
        logger.info(f"[{self.strategy_id}] Evaluation complete: surviving={len(surviving)}, "
                    f"eliminated={len(eliminated)}, session_id={self._cached_session_id}")
        
        factory = get_session_factory()
        try:
            async with factory() as db_session:
                db_session.add(history)
                await db_session.commit()
                logger.debug(f"[{self.strategy_id}] SelectionHistory saved with session_id={self._cached_session_id}")
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
