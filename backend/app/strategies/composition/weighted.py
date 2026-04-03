"""
加权组合策略
通过权重分配将多个策略信号加权求和
"""

import logging
import pandas as pd
from typing import Dict, List, Any, Optional
from .base import StrategyComposer

logger = logging.getLogger(__name__)


class WeightedComposer(StrategyComposer):
    """加权组合策略
    
    通过给每个原子策略分配权重，将信号加权求和
    最终通过阈值判断生成组合信号
    
    Args:
        weights: 权重字典 {strategy_name: weight}
        threshold: 信号阈值，加权和超过此值生成买入/卖出信号
    """
    
    def __init__(
        self, 
        composition_id: str = "weighted",
        weights: Optional[Dict[str, float]] = None,
        threshold: float = 0.5
    ):
        super().__init__(composition_id)
        self.composition_type = "weighted"
        self.weights = weights or {}
        self.threshold = threshold
        
    async def combine_signals(
        self, 
        df: pd.DataFrame,
        atomic_signals: Dict[str, pd.Series]
    ) -> pd.Series:
        """加权组合信号"""
        
        # 验证信号
        if not self.validate_signals(atomic_signals):
            return pd.Series(0, index=df.index)
        
        # 如果没有指定权重，使用等权重
        if not self.weights:
            self.weights = {name: 1.0/len(atomic_signals) for name in atomic_signals.keys()}
        
        # 构建有效权重：只包含存在于 atomic_signals 中的策略
        # 不修改原始 atomic_signals 字典
        valid_weights = {}
        missing_strategies = []
        
        for strategy_name, weight in self.weights.items():
            if strategy_name in atomic_signals:
                valid_weights[strategy_name] = weight
            else:
                missing_strategies.append(strategy_name)
                logger.warning(f"权重中指定的策略 {strategy_name} 不存在于信号中，已从有效权重中排除")
        
        # 检查是否存在有效权重
        if not valid_weights:
            logger.warning("没有有效的权重配置（所有权重指定的策略都不存在于信号中），返回全0信号")
            return pd.Series(0, index=df.index)
        
        # 计算加权和，只使用有效的策略
        weighted_sum = pd.Series(0.0, index=df.index)
        total_weight = 0.0
        
        for strategy_name, signal in atomic_signals.items():
            weight = valid_weights.get(strategy_name, 0.0)
            # 将信号 (-1,0,1) 转换为 (-1,0,1) * weight
            weighted_sum += signal * weight
            total_weight += abs(weight)
        
        # 验证总权重有效性
        if total_weight <= 0:
            logger.warning(f"总权重为 {total_weight}，无法归一化，返回全0信号")
            return pd.Series(0, index=df.index)
        
        # 归一化
        weighted_sum = weighted_sum / total_weight
        
        # 通过阈值生成最终信号
        def _apply_threshold(x):
            if x >= self.threshold:
                return 1
            elif x <= -self.threshold:
                return -1
            else:
                return 0
        
        combined_signal = weighted_sum.apply(_apply_threshold)
        
        logger.info(f"WeightedComposer 组合完成: {len(atomic_signals)}个策略, 阈值={self.threshold}")
        logger.info(f"权重分布: {self.weights}")
        
        # 统计组合结果
        signal_stats = combined_signal.value_counts().to_dict()
        logger.info(f"组合信号统计: 买入={signal_stats.get(1,0)}, 卖出={signal_stats.get(-1,0)}, 持有={signal_stats.get(0,0)}")
        
        return combined_signal
    
    def get_param_space(self) -> Dict[str, List[Any]]:
        """获取加权组合的参数搜索空间"""
        
        # 基础参数空间
        param_space = {
            "threshold": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7],  # 信号阈值
        }
        
        # 权重参数空间 (根据具体策略动态生成)
        # 在实际优化中，权重会在运行时根据原子策略列表动态生成
        
        return param_space
    
    def normalize_weights(self, weights: Dict[str, float]) -> Dict[str, float]:
        """归一化权重，确保权重和为1"""
        total = sum(abs(w) for w in weights.values())
        if total > 0:
            return {k: v/total for k, v in weights.items()}
        return weights
    
    def compute_weight_contribution(
        self, 
        atomic_signals: Dict[str, pd.Series],
        combined_signal: pd.Series
    ) -> Dict[str, float]:
        """计算每个策略对组合信号的贡献度"""
        
        contributions = {}

        for strategy_name, signal in atomic_signals.items():
            # 计算策略信号与组合信号的相关性
            correlation = signal.corr(combined_signal)
            # 计算权重贡献
            weight = self.weights.get(strategy_name, 0.0)
            contributions[strategy_name] = {
                "weight": weight,
                "correlation": correlation if not pd.isna(correlation) else 0.0,
                "signal_strength": signal.abs().mean(),
                "buy_signals": (signal == 1).sum(),
                "sell_signals": (signal == -1).sum()
            }
        
        return contributions