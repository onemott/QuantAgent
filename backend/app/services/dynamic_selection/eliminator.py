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


@dataclass
class RevivalRule:
    """休眠策略复活规则"""
    revival_score_threshold: float = 45.0  # 复活评分阈值（略高于淘汰阈值40，防止频繁切换）
    min_consecutive_high: int = 2  # 连续高于阈值的轮次数
    max_revival_per_round: int = 2  # 每轮最多复活策略数

class StrategyEliminator:
    """策略淘汰器：执行末位淘汰机制"""

    def apply_soft_elimination(
        self,
        ranked_strategies: List[RankedStrategy],
        rule: EliminationRule,
        consecutive_low_counts: Dict[str, int] = None,
        regime_alignment: Dict[str, bool] = None,
    ) -> Tuple[List[RankedStrategy], List[RankedStrategy], Dict[str, str]]:
        consecutive_low_counts = consecutive_low_counts or {}
        regime_alignment = regime_alignment or {}

        surviving = []
        eliminated = []
        reasons = {}

        for rs in ranked_strategies:
            consecutive_low = consecutive_low_counts.get(rs.strategy_id, 0)
            is_absolute_low = rs.score < rule.min_score_threshold
            is_consecutive_extreme = consecutive_low >= rule.min_consecutive_low
            is_regime_mismatch = not regime_alignment.get(rs.strategy_id, True)

            if is_absolute_low and is_consecutive_extreme and is_regime_mismatch:
                eliminated.append(rs)
                reasons[rs.strategy_id] = (
                    f"Extreme weak score ({rs.score:.2f}) with {consecutive_low} consecutive low rounds "
                    "and regime mismatch"
                )
                continue

            surviving.append(rs)

        if len(surviving) < rule.min_strategies:
            eliminated.sort(key=lambda x: x.score, reverse=True)
            need_restore = min(rule.min_strategies - len(surviving), len(eliminated))
            restored = eliminated[:need_restore]
            surviving.extend(restored)
            eliminated = eliminated[need_restore:]
            for rs in restored:
                reasons.pop(rs.strategy_id, None)

        surviving.sort(key=lambda x: x.score, reverse=True)
        eliminated.sort(key=lambda x: x.score, reverse=True)
        return surviving, eliminated, reasons

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

    @staticmethod
    def check_revival(
        hibernating_scores: Dict[str, float],
        consecutive_high_counts: Dict[str, int],
        rule: RevivalRule
    ) -> Tuple[List[str], Dict[str, int], Dict[str, str]]:
        """
        检查休眠策略是否满足复活条件。

        Args:
            hibernating_scores: 休眠策略的当前评分
            consecutive_high_counts: 各休眠策略连续高分计数
            rule: 复活规则

        Returns:
            (revived_ids, updated_counts, revival_reasons)
            - revived_ids: 可复活的策略ID列表
            - updated_counts: 更新后的连续高分计数
            - revival_reasons: 复活原因字典 {strategy_id: reason_string}
        """
        updated_counts = consecutive_high_counts.copy()
        revival_candidates = []

        for strategy_id, score in hibernating_scores.items():
            if score >= rule.revival_score_threshold:
                updated_counts[strategy_id] = updated_counts.get(strategy_id, 0) + 1
            else:
                updated_counts[strategy_id] = 0

            count = updated_counts[strategy_id]
            if count >= rule.min_consecutive_high:
                revival_candidates.append((strategy_id, score, count))

        revival_candidates.sort(key=lambda x: x[1], reverse=True)
        selected = revival_candidates[:rule.max_revival_per_round]

        revived_ids = [s[0] for s in selected]
        revival_reasons = {
            s[0]: f"Score ({s[1]:.2f}) above revival threshold ({rule.revival_score_threshold}) for {s[2]} consecutive rounds"
            for s in selected
        }

        return revived_ids, updated_counts, revival_reasons
