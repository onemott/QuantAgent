"""
投票组合策略
通过多数投票机制组合多个策略信号
"""

import logging
import pandas as pd
import numpy as np
from typing import Dict, List, Any
from .base import StrategyComposer

logger = logging.getLogger(__name__)


class VotingComposer(StrategyComposer):
    """投票组合策略
    
    通过多数投票决定最终信号：
    - 买票 > 阈值: 买入信号
    - 卖票 > 阈值: 卖出信号
    - 否则: 持有
    
    Args:
        threshold: 投票阈值 (0-1)，默认0.5表示简单多数
        veto_power: 是否启用冲突回避机制。当启用且买卖信号同时存在时，
                    为规避风险选择持有，而非传统意义上的"一票否决"
    """
    
    def __init__(
        self, 
        composition_id: str = "voting",
        threshold: float = 0.5,
        veto_power: bool = False
    ):
        super().__init__(composition_id)
        self.composition_type = "voting"
        self.threshold = threshold
        self.veto_power = veto_power
        
    async def combine_signals(
        self, 
        df: pd.DataFrame,
        atomic_signals: Dict[str, pd.Series]
    ) -> pd.Series:
        """投票组合信号"""
        
        # 验证信号
        if not self.validate_signals(atomic_signals):
            return pd.Series(0, index=df.index)
        
        n_strategies = len(atomic_signals)
        
        # 构建信号DataFrame
        signals_df = pd.DataFrame(atomic_signals)
        
        def _row_vote(row):
            """对每行进行投票"""
            total_votes = len(row)
            
            # 统计投票
            buy_votes = (row == 1).sum()
            sell_votes = (row == -1).sum()

            # 冲突回避机制（分歧持有）
            # 当启用 veto_power 且买卖信号同时存在时，为安全起见选择持有
            # 这不是传统意义上的"一票否决"，而是一种风险规避策略：
            # 当策略之间存在分歧时，避免做出可能错误的交易决策
            if self.veto_power:
                if buy_votes > 0 and sell_votes > 0:
                    # 存在买卖分歧，选择持有以规避风险
                    return 0
            
            # 计算投票比例
            buy_ratio = buy_votes / total_votes
            sell_ratio = sell_votes / total_votes
            
            # 应用阈值
            if buy_ratio > self.threshold:      # 严格大于，边界值不触发
                return 1
            elif sell_ratio > self.threshold:    # 严格大于
                return -1
            else:
                return 0
        
        # 逐行应用投票函数
        combined_signal = signals_df.apply(_row_vote, axis=1)
        
        logger.info(f"VotingComposer 组合完成: {n_strategies}个策略, 阈值={self.threshold}, 否决权={self.veto_power}")
        
        # 计算投票统计
        vote_stats = self._compute_vote_statistics(signals_df, combined_signal)
        logger.info(f"投票统计: {vote_stats}")
        
        return combined_signal
    
    def _compute_vote_statistics(
        self, 
        signals_df: pd.DataFrame, 
        combined_signal: pd.Series
    ) -> Dict[str, Any]:
        """计算投票统计信息"""
        
        stats = {
            "total_strategies": signals_df.shape[1],
            "vote_results": {},
            "agreement_levels": {}
        }
        
        # 计算每行的投票一致性
        for idx, row in signals_df.iterrows():
            total = len(row)
            buy_votes = (row == 1).sum()
            sell_votes = (row == -1).sum()
            agreement = max(buy_votes, sell_votes) / total if total > 0 else 0
            
            stats["agreement_levels"][idx] = agreement
        
        # 计算整体一致性
        avg_agreement = np.mean(list(stats["agreement_levels"].values()))
        stats["average_agreement"] = avg_agreement
        
        # 计算各策略的投票模式
        for col in signals_df.columns:
            col_stats = signals_df[col].value_counts().to_dict()
            stats["vote_results"][col] = {
                "buy_votes": col_stats.get(1, 0),
                "sell_votes": col_stats.get(-1, 0),
                "hold_votes": col_stats.get(0, 0),
                "total_votes": len(signals_df)
            }
        
        return stats
    
    def get_param_space(self) -> Dict[str, List[Any]]:
        """获取投票组合的参数搜索空间"""
        
        return {
            "threshold": [0.3, 0.4, 0.5, 0.6, 0.7],  # 投票阈值
            "veto_power": [True, False]  # 是否有一票否决权
        }
    
    def compute_voting_contribution(
        self, 
        atomic_signals: Dict[str, pd.Series],
        combined_signal: pd.Series
    ) -> Dict[str, float]:
        """计算每个策略在投票中的贡献"""
        
        contributions = {}
        signals_df = pd.DataFrame(atomic_signals)
        
        for strategy_name, signal in atomic_signals.items():
            # 计算策略与最终决策的一致性
            agreement = (signal == combined_signal).mean()
            
            # 计算策略的影响力 (策略改变投票时是否影响最终结果)
            influence = self._compute_strategy_influence(
                signals_df, combined_signal, strategy_name
            )
            
            contributions[strategy_name] = {
                "agreement_rate": agreement,
                "influence_score": influence,
                "signal_frequency": signal.abs().mean(),
                "buy_rate": (signal == 1).mean(),
                "sell_rate": (signal == -1).mean()
            }
        
        return contributions
    
    def _compute_strategy_influence(
        self, 
        signals_df: pd.DataFrame,
        combined_signal: pd.Series,
        strategy_name: str
    ) -> float:
        """计算单个策略的影响力"""
        
        # 模拟移除该策略后的投票结果
        other_strategies = [col for col in signals_df.columns if col != strategy_name]
        
        if not other_strategies:
            return 1.0  # 唯一策略，影响力最大
        
        # 使用其他策略重新投票
        other_signals = signals_df[other_strategies]

        def _other_vote(row):
            buy_votes = (row == 1).sum()
            sell_votes = (row == -1).sum()
            total = len(row)
            
            buy_ratio = buy_votes / total if total > 0 else 0
            sell_ratio = sell_votes / total if total > 0 else 0
            
            if buy_ratio >= self.threshold:
                return 1
            elif sell_ratio >= self.threshold:
                return -1
            return 0
        
        other_combined = other_signals.apply(_other_vote, axis=1)
        
        # 计算影响力 (原始结果与移除后结果的不一致比例)
        influence = (combined_signal != other_combined).mean()
        
        return influence