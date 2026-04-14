from typing import List, Tuple, Dict
from dataclasses import dataclass
from .ranker import RankedStrategy

@dataclass
class EliminationRule:
    """策略淘汰规则配置"""
    min_score_threshold: float = 40.0  # 低于此分绝对淘汰
    elimination_ratio: float = 0.2     # 淘汰末尾比例
    min_consecutive_low: int = 3       # 连续低分次数
    low_score_threshold: float = 50.0  # 连续低分判断阈值
    min_strategies: int = 3            # 最少保留策略数

    def __post_init__(self):
        """Validate field ranges after initialization."""
        if not (0 <= self.min_score_threshold <= 100):
            raise ValueError(
                f"min_score_threshold must be between 0 and 100, got {self.min_score_threshold}"
            )
        if not (0 <= self.elimination_ratio <= 1):
            raise ValueError(
                f"elimination_ratio must be between 0 and 1, got {self.elimination_ratio}"
            )
        if self.min_consecutive_low < 1:
            raise ValueError(
                f"min_consecutive_low must be >= 1, got {self.min_consecutive_low}"
            )
        if not (0 <= self.low_score_threshold <= 100):
            raise ValueError(
                f"low_score_threshold must be between 0 and 100, got {self.low_score_threshold}"
            )
        if self.min_strategies < 1:
            raise ValueError(
                f"min_strategies must be >= 1, got {self.min_strategies}"
            )

class StrategyEliminator:
    """策略淘汰器：执行末位淘汰机制"""

    def apply_elimination(
        self,
        ranked_strategies: List[RankedStrategy],
        rule: EliminationRule,
        consecutive_low_counts: Dict[str, int] = None
    ) -> Tuple[List[RankedStrategy], List[RankedStrategy], Dict[str, str]]:
        """
        应用淘汰规则，区分保留与淘汰的策略。
        
        :param ranked_strategies: 已经排序过的策略列表
        :param rule: 淘汰规则配置对象
        :param consecutive_low_counts: 各策略当前连续低于低分阈值的次数字典
        :return: (surviving_strategies, eliminated_strategies, elimination_reasons_dict)
        """
        consecutive_low_counts = consecutive_low_counts or {}
        surviving = []
        eliminated = []
        reasons = {}
        
        for rs in ranked_strategies:
            # 规则一：绝对低分淘汰
            if rs.score < rule.min_score_threshold:
                eliminated.append(rs)
                reasons[rs.strategy_id] = f"Score ({rs.score:.2f}) below absolute threshold ({rule.min_score_threshold})"
                continue
                
            # 规则三：连续低分淘汰
            consecutive_low = consecutive_low_counts.get(rs.strategy_id, 0)
            if consecutive_low >= rule.min_consecutive_low:
                eliminated.append(rs)
                reasons[rs.strategy_id] = f"Consecutive low scores ({consecutive_low} times >= {rule.min_consecutive_low})"
                continue
                
            surviving.append(rs)
            
        # 规则二：相对比例淘汰
        max_eliminate = int(len(ranked_strategies) * rule.elimination_ratio)
        if len(eliminated) < max_eliminate:
            # 从剩下的存活策略中，淘汰末尾表现最差的
            need_elim = max_eliminate - len(eliminated)
            # 因为 surviving 保持了 ranked_strategies 的降序，末尾就是最差的
            additional_elim = surviving[-need_elim:] if need_elim > 0 else []
            for rs in additional_elim:
                eliminated.append(rs)
                reasons[rs.strategy_id] = f"Eliminated by relative ratio (bottom {rule.elimination_ratio*100:.0f}%)"
            
            surviving = surviving[:-need_elim] if need_elim > 0 else surviving
            
        # 规则四：最小保留策略数
        if len(surviving) < rule.min_strategies:
            # 存活数量不够时，从淘汰列表中按得分高低捞回
            eliminated.sort(key=lambda x: x.score, reverse=True)
            need_restore = min(rule.min_strategies - len(surviving), len(eliminated))
            restored = eliminated[:need_restore]
            surviving.extend(restored)
            eliminated = eliminated[need_restore:]
            
            # 清除捞回策略的淘汰原因
            for rs in restored:
                reasons.pop(rs.strategy_id, None)
                    
        # 确保返回时重新按得分降序排列
        surviving.sort(key=lambda x: x.score, reverse=True)
        eliminated.sort(key=lambda x: x.score, reverse=True)
        
        return surviving, eliminated, reasons
