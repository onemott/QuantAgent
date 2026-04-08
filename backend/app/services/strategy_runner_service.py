"""
Strategy Runner Service
Executes quantitative strategies periodically and generates trading signals.
Signals are published to NATS 'trade.signal' for execution by TradingWorker.
"""

import asyncio
import json
import logging
import nats
import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any

from app.core.config import settings
from app.services.strategy_templates import build_signal_func
from app.services.binance_service import binance_service
from app.services.database import get_session_factory
from app.models.db_models import PerformanceMetric, SelectionHistory
from app.services.dynamic_selection.evaluator import StrategyEvaluator
from app.services.dynamic_selection.ranker import StrategyRanker
from app.services.dynamic_selection.eliminator import StrategyEliminator, EliminationRule
from app.services.dynamic_selection.weight_allocator import WeightAllocator
from app.strategies.composition.weighted import WeightedComposer

logger = logging.getLogger(__name__)

# Active strategies to run in paper trading
ACTIVE_STRATEGIES = [
    {
        "strategy_id": "auto_trend_ma",
        "strategy_type": "ma",
        "symbol": "BTCUSDT",
        "interval": "1h",
        "params": {"fast_period": 10, "slow_period": 30},
        "quantity": 0.01,
    },
    {
        "strategy_id": "auto_reversion_rsi",
        "strategy_type": "rsi",
        "symbol": "ETHUSDT",
        "interval": "1h",
        "params": {"rsi_period": 14, "oversold": 30, "overbought": 70},
        "quantity": 0.1,
    },
    {
        "strategy_id": "auto_volatility_boll",
        "strategy_type": "boll",
        "symbol": "SOLUSDT",
        "interval": "1h",
        "params": {"period": 20, "std_dev": 2.0},
        "quantity": 1.0,
    }
]

class StrategyRunnerService:
    def __init__(self):
        self.nc = None
        self.running = False
        
        # 动态选择与组合组件
        self.evaluator = StrategyEvaluator()
        self.ranker = StrategyRanker()
        self.eliminator = StrategyEliminator()
        self.allocator = WeightAllocator()
        
        # 初始化加权组合器
        self.composer = WeightedComposer(composition_id="dynamic_weighted")
        self.last_evaluation_time = None
        self.evaluation_interval = timedelta(hours=24)  # 每天评估一次

    async def _connect_nats(self):
        if self.nc and self.nc.is_connected:
            return
        try:
            self.nc = await nats.connect(settings.NATS_URL)
            logger.info("StrategyRunner connected to NATS")
        except Exception as e:
            logger.error(f"Failed to connect to NATS: {e}")

    async def run_all_strategies(self):
        """Fetch data, generate signals, and publish for all active strategies."""
        logger.info(f"Running {len(ACTIVE_STRATEGIES)} automated strategies...")
        await self._connect_nats()
        
        # 1. 周期性执行动态评估并更新权重
        now = datetime.now(timezone.utc)
        if self.last_evaluation_time is None or (now - self.last_evaluation_time) >= self.evaluation_interval:
            await self._evaluate_and_update_weights(now)
            self.last_evaluation_time = now

        # 2. 收集所有原子策略信号
        atomic_signals_current = {}
        strategy_df_map = {}
        for config in ACTIVE_STRATEGIES:
            try:
                signal_info = await self._get_strategy_signal(config)
                if signal_info:
                    strategy_id = config["strategy_id"]
                    atomic_signals_current[strategy_id] = signal_info["latest_signal"]
                    strategy_df_map[strategy_id] = signal_info
            except Exception as e:
                logger.error(f"Error running strategy {config['strategy_id']}: {e}")

        # 3. 使用 WeightedComposer 组合信号并发布 (可选: 独立发布组合信号)
        # 如果需要将组合信号作为单一交易依据，可以在这里计算并发布
        if atomic_signals_current and self.composer.weights:
            await self._publish_composite_signal(atomic_signals_current, strategy_df_map)

    async def _evaluate_and_update_weights(self, now: datetime):
        """执行动态策略评估、淘汰和权重分配"""
        logger.info("开始执行动态策略评估和权重更新...")
        from sqlalchemy import select
        from app.services.database import get_db
        try:
            async with get_db() as db:
                evaluations = []
                for config in ACTIVE_STRATEGIES:
                    strategy_id = config["strategy_id"]
                    # 获取最近的性能指标 (这里假设有一个按 strategy_id 查询的方法，实际中可能是通过其他方式)
                    # 简化处理：假设数据库中有 PerformanceMetric 记录
                    stmt = select(PerformanceMetric).filter(
                        PerformanceMetric.period == "daily"
                    ).order_by(PerformanceMetric.created_at.desc())
                    result = await db.execute(stmt)
                    metric = result.scalars().first()
                    
                    if metric:
                        evaluation = self.evaluator.evaluate(
                            strategy_id=strategy_id,
                            performance=metric,
                            window_start=now - timedelta(days=30),
                            window_end=now
                        )
                        evaluations.append(evaluation)
                
                if not evaluations:
                    logger.warning("没有足够的性能数据进行动态评估，跳过权重更新")
                    return

                # 排名
                # 注意：目前 rank 方法需要第二个参数吗？
                ranked_strategies = self.ranker.rank_evaluations(evaluations)
                
                # 淘汰
                # 注意：目前 eliminate 方法在 StrategyEliminator 是 apply_elimination 
                # 但旧代码是 eliminate(ranked_strategies)
                # 从 eliminator.py 来看： apply_elimination(ranked_strategies, rule, consecutive_low_counts)
                # 假设 StrategyEliminator 初始化时传了 rules
                surviving, eliminated, reasons = self.eliminator.apply_elimination(
                    ranked_strategies, 
                    self.eliminator.rules[0] if hasattr(self.eliminator, 'rules') and self.eliminator.rules else EliminationRule()
                )
                logger.info(f"策略淘汰结果: 存活 {len(surviving)} 个, 淘汰 {len(eliminated)} 个")

                # 权重分配
                new_weights = self.allocator.allocate_weights(surviving, method="score_based")
                
                # 更新组合器权重
                self.composer.update_weights(new_weights)

                # 记录选择历史
                history = SelectionHistory(
                    evaluation_date=now,
                    total_strategies=len(ranked_strategies),
                    surviving_count=len(surviving),
                    eliminated_count=len(eliminated),
                    eliminated_strategy_ids=[s.strategy_id for s in eliminated],
                    elimination_reasons=reasons,
                    strategy_weights=new_weights
                )
                db.add(history)
                # await db.commit() # get_db handles commit
                logger.info("动态策略评估和权重更新完成")

        except Exception as e:
            logger.error(f"动态评估与权重更新失败: {e}")

    async def _get_strategy_signal(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """获取单个策略的信号信息但不立即发布"""
        strategy_id = config["strategy_id"]
        strategy_type = config["strategy_type"]
        symbol = config["symbol"]
        interval = config["interval"]
        params = config["params"]
        quantity = config["quantity"]

        df = await binance_service.get_klines_dataframe(symbol, interval, limit=100)
        if df is None or len(df) < 50:
            logger.warning(f"Insufficient data for {symbol} {interval}")
            return None

        signal_func = build_signal_func(strategy_type, params)
        
        import inspect
        if inspect.iscoroutinefunction(signal_func):
            signals = await signal_func(df)
        else:
            signals = signal_func(df)

        latest_signal = int(signals.iloc[-1])
        logger.debug(f"Strategy {strategy_id} signal for {symbol}: {latest_signal}")

        return {
            "strategy_id": strategy_id,
            "symbol": symbol,
            "quantity": quantity,
            "latest_signal": latest_signal,
            "current_price": float(df["close"].iloc[-1]),
            "signals": signals, # pd.Series
            "df": df
        }

    async def _publish_composite_signal(self, atomic_signals_current: Dict[str, int], strategy_df_map: Dict[str, Any]):
        """根据最新信号加权组合并发布"""
        # 构建仅含最新信号的Series，适配 combine_signals 或直接加权
        # WeightedComposer的 combine_signals 期望的是 pd.Series 字典，这里我们传入单个时间点的Series
        # 为简便起见，直接在当前点进行加权
        
        weighted_sum = 0.0
        total_weight = 0.0
        for strategy_id, signal in atomic_signals_current.items():
            weight = self.composer.weights.get(strategy_id, 0.0)
            weighted_sum += signal * weight
            total_weight += abs(weight)

        if total_weight > 0:
            normalized_score = weighted_sum / total_weight
            
            combined_signal = 0
            if normalized_score >= self.composer.threshold:
                combined_signal = 1
            elif normalized_score <= -self.composer.threshold:
                combined_signal = -1

            if combined_signal != 0:
                # 使用第一个可用标的信息发布（假设同标的组合）
                first_strategy = list(strategy_df_map.values())[0]
                symbol = first_strategy["symbol"]
                current_price = first_strategy["current_price"]
                quantity = first_strategy["quantity"] # 或组合逻辑分配数量
                
                side = "BUY" if combined_signal == 1 else "SELL"
                payload = {
                    "symbol": symbol,
                    "side": side,
                    "quantity": quantity,
                    "price": current_price,
                    "strategy_id": "dynamic_weighted",
                    "order_type": "MARKET",
                    "client_order_id": f"auto-comp-{int(datetime.now(timezone.utc).timestamp())}"
                }
                if self.nc:
                    await self.nc.publish("trade.signal", json.dumps(payload).encode())
                    logger.info(f"Published composite {side} signal for {symbol} @ {current_price}")

strategy_runner_service = StrategyRunnerService()
