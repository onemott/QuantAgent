"""
策略组合优化服务
提供加权组合和投票组合的参数优化功能
"""

import logging
import asyncio
import itertools
import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional, Tuple, Union
from datetime import datetime

from app.services.strategy_templates import get_all_templates_meta, build_signal_func
from app.services.binance_service import binance_service
from app.services.clickhouse_service import clickhouse_service
from app.services.backtester.event_driven import EventDrivenBacktester
from app.strategies.composition.factory import CompositionFactory
from app.strategies.composition.weighted import WeightedComposer
from app.strategies.composition.voting import VotingComposer

logger = logging.getLogger(__name__)


class CompositionOptimizer:
    """策略组合优化器"""
    
    def __init__(self):
        self.available_strategies = get_all_templates_meta()
    
    async def optimize_composition(
        self,
        atomic_strategies: List[str],           # 候选原子策略列表
        composition_type: str,                  # 组合类型: 'weighted' 或 'voting'
        symbol: str,                           # 标的
        interval: str,                         # 时间周期
        data_limit: int = 500,                 # 数据量限制
        initial_capital: float = 10000.0,      # 初始资金
        param_grid: Optional[Dict[str, List[Any]]] = None,  # 自定义参数网格
        max_combinations: int = 50,            # 最大组合数
        use_clickhouse: bool = True            # 是否使用ClickHouse数据
    ) -> Dict[str, Any]:
        """优化策略组合
        
        Args:
            atomic_strategies: 原子策略列表，如 ['ma', 'rsi', 'boll']
            composition_type: 组合类型
            symbol: 交易标的
            interval: 时间周期
            data_limit: 数据量限制
            initial_capital: 初始资金
            param_grid: 自定义参数网格
            max_combinations: 最大参数组合数
            use_clickhouse: 是否使用ClickHouse数据
        
        Returns:
            优化结果字典
        """
        
        logger.info(f"开始优化策略组合: {composition_type}")
        logger.info(f"原子策略: {atomic_strategies}")
        logger.info(f"标的: {symbol}, 周期: {interval}")
        
        # 1. 获取历史数据
        df = await self._fetch_historical_data(
            symbol, interval, data_limit, use_clickhouse
        )
        if df is None or len(df) < 50:
            raise ValueError("历史数据不足，无法进行优化")
        
        logger.info(f"获取到 {len(df)} 条历史数据")
        
        # 2. 运行所有原子策略获取信号
        atomic_signals = await self._run_atomic_strategies(
            df, atomic_strategies
        )
        
        if not atomic_signals:
            raise ValueError("没有有效的原子策略信号")
        
        logger.info(f"生成 {len(atomic_signals)} 个原子策略信号")
        
        # 3. 根据组合类型进行优化
        if composition_type == "weighted":
            result = await self._optimize_weighted(
                df, atomic_signals, atomic_strategies, 
                initial_capital, param_grid, max_combinations
            )
        elif composition_type == "voting":
            result = await self._optimize_voting(
                df, atomic_signals, atomic_strategies,
                initial_capital, param_grid, max_combinations
            )
        else:
            raise ValueError(f"不支持的组合类型: {composition_type}")
        
        # 4. 添加元数据
        result.update({
            "composition_type": composition_type,
            "atomic_strategies": atomic_strategies,
            "symbol": symbol,
            "interval": interval,
            "data_points": len(df),
            "optimization_time": datetime.utcnow().isoformat()
        })
        
        logger.info(f"组合优化完成，最佳夏普比率: {result.get('best_sharpe', 0):.4f}")
        
        return result
    
    async def _fetch_historical_data(
        self, 
        symbol: str, 
        interval: str, 
        limit: int,
        use_clickhouse: bool
    ) -> Optional[pd.DataFrame]:
        """获取历史数据"""
        
        # 标准化符号格式
        if "/" not in symbol:
            symbol_ccxt = f"{symbol[:-4]}/USDT" if symbol.endswith("USDT") else symbol
        else:
            symbol_ccxt = symbol
            symbol = symbol.replace("/", "")
        
        try:
            if use_clickhouse:
                # 尝试从ClickHouse获取数据
                df = await clickhouse_service.get_klines_dataframe(
                    symbol=symbol,
                    interval=interval,
                    limit=limit
                )
                if df is not None and len(df) >= 50:
                    logger.info(f"从ClickHouse获取 {len(df)} 条数据")
                    return df
            
            # 回退到Binance API
            logger.info(f"从Binance API获取数据: {symbol_ccxt}")
            df = await binance_service.get_klines_dataframe(
                symbol_ccxt, interval, limit=limit
            )
            return df
            
        except Exception as e:
            logger.error(f"获取历史数据失败: {e}")
            return None
    
    async def _run_atomic_strategies(
        self, 
        df: pd.DataFrame, 
        strategy_types: List[str]
    ) -> Dict[str, pd.Series]:
        """运行原子策略获取信号"""
        
        atomic_signals = {}
        
        for strategy_type in strategy_types:
            try:
                # 获取策略默认参数
                from app.services.strategy_templates import get_template_default_params
                params = get_template_default_params(strategy_type)
                
                # 构建信号函数
                signal_func = build_signal_func(strategy_type, params)
                
                # 生成信号
                signals = signal_func(df)
                
                # 确保信号是Series类型
                if isinstance(signals, pd.Series):
                    atomic_signals[strategy_type] = signals
                else:
                    logger.warning(f"策略 {strategy_type} 返回非Series信号: {type(signals)}")
                    
            except Exception as e:
                logger.warning(f"策略 {strategy_type} 执行失败: {e}")
                continue
        
        return atomic_signals
    
    async def _optimize_weighted(
        self,
        df: pd.DataFrame,
        atomic_signals: Dict[str, pd.Series],
        atomic_strategies: List[str],
        initial_capital: float,
        param_grid: Optional[Dict[str, List[Any]]],
        max_combinations: int
    ) -> Dict[str, Any]:
        """优化加权组合"""
        
        # 使用默认参数网格或自定义网格
        if param_grid is None:
            param_grid = {
                "threshold": [0.3, 0.4, 0.5, 0.6],
            }
        
        # 生成权重组合 (简化: 使用等权重或简单权重分布)
        # 实际应用中可以使用更复杂的权重生成算法
        weight_combinations = self._generate_weight_combinations(
            atomic_strategies, max_combinations // len(param_grid["threshold"])
        )
        
        # 生成所有参数组合
        all_combinations = []
        for weights in weight_combinations:
            for threshold in param_grid["threshold"]:
                all_combinations.append({
                    "weights": weights,
                    "threshold": threshold
                })
        
        # 限制组合数量
        if len(all_combinations) > max_combinations:
            all_combinations = all_combinations[:max_combinations]
        
        logger.info(f"加权组合优化: 测试 {len(all_combinations)} 个参数组合")
        
        # 评估所有组合
        results = []
        for i, params in enumerate(all_combinations):
            try:
                # 创建组合器
                composer = WeightedComposer(
                    composition_id=f"weighted_opt_{i}",
                    weights=params["weights"],
                    threshold=params["threshold"]
                )
                
                # 生成组合信号
                combined_signal = await composer.combine_signals(df, atomic_signals)
                
                # 回测评估
                performance = await self._evaluate_composition(
                    df, combined_signal, initial_capital
                )
                
                if performance:
                    results.append({
                        "params": params,
                        "performance": performance,
                        "sharpe": performance["sharpe_ratio"],
                        "total_return": performance["total_return"],
                        "max_drawdown": performance["max_drawdown"]
                    })
                    
            except Exception as e:
                logger.warning(f"参数组合 {params} 评估失败: {e}")
                continue
        
        # 排序并返回最佳结果
        if not results:
            raise ValueError("没有有效的优化结果")
        
        # 按夏普比率排序
        results.sort(key=lambda x: x["sharpe"], reverse=True)
        
        best_result = results[0]
        
        return {
            "best_params": best_result["params"],
            "best_performance": best_result["performance"],
            "best_sharpe": best_result["sharpe"],
            "best_return": best_result["total_return"],
            "best_drawdown": best_result["max_drawdown"],
            "all_results": results[:20],  # 返回前20个结果
            "total_combinations_tested": len(all_combinations),
            "valid_results": len(results)
        }
    
    async def _optimize_voting(
        self,
        df: pd.DataFrame,
        atomic_signals: Dict[str, pd.Series],
        atomic_strategies: List[str],
        initial_capital: float,
        param_grid: Optional[Dict[str, List[Any]]],
        max_combinations: int
    ) -> Dict[str, Any]:
        """优化投票组合"""
        
        # 使用默认参数网格或自定义网格
        if param_grid is None:
            param_grid = {
                "threshold": [0.3, 0.4, 0.5, 0.6, 0.7],
                "veto_power": [True, False]
            }
        
        # 生成所有参数组合
        param_names = list(param_grid.keys())
        param_values = [param_grid[name] for name in param_names]
        
        all_combinations = []
        for values in itertools.product(*param_values):
            params = dict(zip(param_names, values))
            all_combinations.append(params)
        
        # 限制组合数量
        if len(all_combinations) > max_combinations:
            all_combinations = all_combinations[:max_combinations]
        
        logger.info(f"投票组合优化: 测试 {len(all_combinations)} 个参数组合")
        
        # 评估所有组合
        results = []
        for i, params in enumerate(all_combinations):
            try:
                # 创建组合器
                composer = VotingComposer(
                    composition_id=f"voting_opt_{i}",
                    threshold=params["threshold"],
                    veto_power=params.get("veto_power", False)
                )
                
                # 生成组合信号
                combined_signal = await composer.combine_signals(df, atomic_signals)
                
                # 回测评估
                performance = await self._evaluate_composition(
                    df, combined_signal, initial_capital
                )
                
                if performance:
                    results.append({
                        "params": params,
                        "performance": performance,
                        "sharpe": performance["sharpe_ratio"],
                        "total_return": performance["total_return"],
                        "max_drawdown": performance["max_drawdown"]
                    })
                    
            except Exception as e:
                logger.warning(f"参数组合 {params} 评估失败: {e}")
                continue
        
        # 排序并返回最佳结果
        if not results:
            raise ValueError("没有有效的优化结果")
        
        # 按夏普比率排序
        results.sort(key=lambda x: x["sharpe"], reverse=True)
        
        best_result = results[0]
        
        return {
            "best_params": best_result["params"],
            "best_performance": best_result["performance"],
            "best_sharpe": best_result["sharpe"],
            "best_return": best_result["total_return"],
            "best_drawdown": best_result["max_drawdown"],
            "all_results": results[:20],  # 返回前20个结果
            "total_combinations_tested": len(all_combinations),
            "valid_results": len(results)
        }
    
    def _generate_weight_combinations(
        self, 
        strategy_names: List[str], 
        n_combinations: int
    ) -> List[Dict[str, float]]:
        """生成权重组合
        
        简化的权重生成方法：
        1. 等权重
        2. 聚焦权重（某个策略权重较高）
        3. 随机权重
        
        Args:
            strategy_names: 策略名称列表
            n_combinations: 需要生成的组合数
        
        Returns:
            权重组合列表
        """
        
        n_strategies = len(strategy_names)
        if n_strategies == 0:
            return []
        
        weight_combinations = []
        
        # 1. 等权重
        equal_weights = {name: 1.0/n_strategies for name in strategy_names}
        weight_combinations.append(equal_weights)
        
        # 2. 聚焦权重（每个策略轮流作为主要策略）
        for focus_idx in range(min(n_strategies, n_combinations-1)):
            weights = {}
            focus_weight = 0.7  # 主要策略权重
            other_weight = (1.0 - focus_weight) / (n_strategies - 1) if n_strategies > 1 else 0
            
            for i, name in enumerate(strategy_names):
                if i == focus_idx:
                    weights[name] = focus_weight
                else:
                    weights[name] = other_weight
            
            weight_combinations.append(weights)
        
        # 3. 随机权重（如果需要更多组合）
        import random
        while len(weight_combinations) < n_combinations:
            weights = {}
            # 生成随机权重
            random_weights = [random.random() for _ in range(n_strategies)]
            total = sum(random_weights)
            
            # 归一化
            for i, name in enumerate(strategy_names):
                weights[name] = random_weights[i] / total if total > 0 else 1.0/n_strategies
            
            weight_combinations.append(weights)
        
        return weight_combinations[:n_combinations]
    
    async def _evaluate_composition(
        self,
        df: pd.DataFrame,
        combined_signal: pd.Series,
        initial_capital: float,
        commission: float = 0.001
    ) -> Optional[Dict[str, Any]]:
        """评估组合策略性能"""
        
        try:
            # 使用事件驱动回测器
            backtester = EventDrivenBacktester(
                df=df,
                signal_func=lambda df: combined_signal,
                initial_capital=initial_capital,
                commission=commission
            )
            
            result = backtester.run()
            
            # 提取关键指标
            performance = {
                "total_return": result.get("total_return", 0.0),
                "annual_return": result.get("annual_return", 0.0),
                "max_drawdown": result.get("max_drawdown", 0.0),
                "sharpe_ratio": result.get("sharpe_ratio", 0.0),
                "win_rate": result.get("win_rate", 0.0),
                "profit_factor": result.get("profit_factor", 0.0),
                "total_trades": result.get("total_trades", 0),
                "final_capital": result.get("final_capital", initial_capital)
            }
            
            return performance
            
        except Exception as e:
            logger.warning(f"组合评估失败: {e}")
            return None
    
    async def compare_composition_types(
        self,
        atomic_strategies: List[str],
        symbol: str,
        interval: str,
        data_limit: int = 500,
        initial_capital: float = 10000.0
    ) -> Dict[str, Any]:
        """比较不同组合类型的表现"""
        
        comparison_results = {}
        
        # 获取历史数据
        df = await self._fetch_historical_data(
            symbol, interval, data_limit, use_clickhouse=True
        )
        if df is None or len(df) < 50:
            raise ValueError("历史数据不足")
        
        # 获取原子策略信号
        atomic_signals = await self._run_atomic_strategies(df, atomic_strategies)
        
        # 测试每种组合类型
        composition_types = ["weighted", "voting"]
        
        for comp_type in composition_types:
            try:
                logger.info(f"测试组合类型: {comp_type}")
                
                if comp_type == "weighted":
                    # 使用等权重作为基准
                    weights = {name: 1.0/len(atomic_strategies) for name in atomic_strategies}
                    composer = WeightedComposer(
                        composition_id=f"compare_{comp_type}",
                        weights=weights,
                        threshold=0.5
                    )
                else:  # voting
                    composer = VotingComposer(
                        composition_id=f"compare_{comp_type}",
                        threshold=0.5,
                        veto_power=False
                    )
                
                # 生成组合信号
                combined_signal = await composer.combine_signals(df, atomic_signals)
                
                # 评估性能
                performance = await self._evaluate_composition(
                    df, combined_signal, initial_capital
                )
                
                if performance:
                    comparison_results[comp_type] = {
                        "performance": performance,
                        "composer_params": {
                            "type": comp_type,
                            "params": composer.__dict__
                        }
                    }
                    
            except Exception as e:
                logger.warning(f"组合类型 {comp_type} 测试失败: {e}")
                comparison_results[comp_type] = {
                    "error": str(e),
                    "performance": None
                }
        
        # 添加原子策略的独立表现
        atomic_performances = {}
        for strategy_name, signal in atomic_signals.items():
            perf = await self._evaluate_composition(df, signal, initial_capital)
            if perf:
                atomic_performances[strategy_name] = perf
        
        comparison_results["atomic_strategies"] = atomic_performances
        
        return comparison_results