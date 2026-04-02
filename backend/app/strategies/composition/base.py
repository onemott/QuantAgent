"""
策略组合器抽象基类
提供统一的接口将多个原子策略信号组合为单一交易信号
"""

import logging
import pandas as pd
import numpy as np
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Tuple, Union

logger = logging.getLogger(__name__)


class StrategyComposer(ABC):
    """策略组合器抽象基类"""
    
    def __init__(self, composition_id: str):
        self.composition_id = composition_id
        self.composition_type = self.__class__.__name__.replace("Composer", "").lower()
        
    @abstractmethod
    async def combine_signals(
        self, 
        df: pd.DataFrame,
        atomic_signals: Dict[str, pd.Series]  # {strategy_name: signal_series}
    ) -> pd.Series:
        """将多个策略信号组合为单一信号
        
        Args:
            df: 原始K线数据
            atomic_signals: 原子策略信号字典
            
        Returns:
            combined_signal: 组合后的信号序列 (-1, 0, 1)
        """
        pass
    
    @abstractmethod
    def get_param_space(self) -> Dict[str, List[Any]]:
        """返回参数搜索空间
        
        Returns:
            param_space: 参数名到可选值列表的映射
        """
        pass
    
    def set_parameters(self, params: Dict[str, Any]):
        """设置组合参数"""
        for key, value in params.items():
            if hasattr(self, key):
                setattr(self, key, value)
            else:
                logger.warning(f"参数 {key} 不在组合器 {self.composition_type} 中")
    
    def validate_signals(self, atomic_signals: Dict[str, pd.Series]) -> bool:
        """验证原子策略信号的有效性"""
        if not atomic_signals:
            logger.error("原子策略信号为空")
            return False
        
        # 检查所有信号长度一致
        signal_lengths = [len(signal) for signal in atomic_signals.values()]
        if len(set(signal_lengths)) > 1:
            logger.error(f"原子策略信号长度不一致: {signal_lengths}")
            return False
        
        # 检查信号值范围
        for name, signal in atomic_signals.items():
            unique_values = set(signal.unique())
            if not unique_values.issubset({-1, 0, 1}):
                logger.warning(f"策略 {name} 信号包含非标准值: {unique_values}")
        
        return True
    
    def compute_signal_statistics(self, atomic_signals: Dict[str, pd.Series]) -> Dict[str, Any]:
        """计算信号统计信息"""
        stats = {
            "total_strategies": len(atomic_signals),
            "strategy_names": list(atomic_signals.keys()),
            "signal_counts": {},
            "agreement_rates": {}
        }
        
        for name, signal in atomic_signals.items():
            # 统计各信号数量
            signal_counts = signal.value_counts().to_dict()
            stats["signal_counts"][name] = {
                "buy": signal_counts.get(1, 0),
                "sell": signal_counts.get(-1, 0),
                "hold": signal_counts.get(0, 0),
                "total": len(signal)
            }
        
        # 计算策略间一致性
        if len(atomic_signals) > 1:
            signal_df = pd.DataFrame(atomic_signals)
            agreement = (signal_df.abs().sum(axis=1) / len(atomic_signals)).mean()
            stats["average_agreement"] = float(agreement)
        
        return stats