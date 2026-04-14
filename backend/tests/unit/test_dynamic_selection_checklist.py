import pytest
import asyncio
import pandas as pd
from datetime import datetime, timezone

from app.models.db_models import PerformanceMetric, TradePair, PaperTrade
from app.services.dynamic_selection.evaluator import StrategyEvaluator
from app.services.dynamic_selection.eliminator import StrategyEliminator, EliminationRule
from app.services.dynamic_selection.weight_allocator import WeightAllocator
from app.services.dynamic_selection.ranker import RankedStrategy
from app.models.db_models import StrategyEvaluation
from app.strategies.composition.weighted import WeightedComposer

def test_evaluator_scoring():
    """1. evaluator.py 评分计算 (构造已知 PaperTrade + TradePair，断言得分)"""
    # 构造已知 TradePair 模拟交易结果
    trade_pairs = [
        TradePair(pnl=100, status="CLOSED"),
        TradePair(pnl=-50, status="CLOSED"),
        TradePair(pnl=200, status="CLOSED"),
        TradePair(pnl=150, status="CLOSED")
    ]
    
    total_trades = len(trade_pairs)
    win_rate = sum(1 for tp in trade_pairs if tp.pnl > 0) / total_trades
    
    # 基于 TradePair 构造 PerformanceMetric (VirtualBus 输出小数格式)
    perf = PerformanceMetric(
        annualized_return=0.10,  # 10% 以小数 0.10 存储
        max_drawdown_pct=0.15,   # 15% 以小数 0.15 存储
        sharpe_ratio=1.5,
        win_rate=win_rate,       # 0.75 (75%)
        total_trades=total_trades # 4
    )
    
    evaluator = StrategyEvaluator()
    scores = evaluator.calculate_scores(perf)
    
    # 验证得分
    # return_score: (0.1 / 0.2) * 30 = 15.0
    assert scores["return_score"] == 15.0
    # risk_score: (1 - 0.15/0.3) * 25 = 12.5
    assert scores["risk_score"] == 12.5
    # sharpe_score: (1.5 / 2.0) * 25 = 18.75
    assert scores["risk_adjusted_score"] == 18.75
    # stability_score: 0.75 * 10 = 7.5
    assert scores["stability_score"] == 7.5
    # efficiency_score: (4 / 10.0) * 10 = 4.0
    assert scores["efficiency_score"] == 4.0
    # total_score = 15.0 + 12.5 + 18.75 + 7.5 + 4.0 = 57.75
    assert scores["total_score"] == 57.75

def test_eliminator_logic():
    """2. eliminator.py 策略剔除 (输入策略分数，验证低分被剔除)"""
    eliminator = StrategyEliminator()
    # 绝对分数低于20剔除，淘汰末尾50%
    rule = EliminationRule(min_score_threshold=20.0, elimination_ratio=0.5, min_strategies=1)
    
    strategies = [
        RankedStrategy("s1", 80.0, 1, StrategyEvaluation(strategy_id="s1", total_score=80.0)),
        RankedStrategy("s2", 60.0, 2, StrategyEvaluation(strategy_id="s2", total_score=60.0)),
        RankedStrategy("s3", 50.0, 3, StrategyEvaluation(strategy_id="s3", total_score=50.0)),
        RankedStrategy("s4", 15.0, 4, StrategyEvaluation(strategy_id="s4", total_score=15.0)), # 低于20，被剔除
    ]
    
    surviving, eliminated, reasons = eliminator.apply_elimination(strategies, rule)
    
    # s4 会因为低于20被绝对剔除
    # max_eliminate = int(4 * 0.5) = 2。还需要淘汰1个（最差的 s3）
    assert len(surviving) == 2
    assert "s1" in [s.strategy_id for s in surviving]
    assert "s2" in [s.strategy_id for s in surviving]
    assert len(eliminated) == 2
    assert "s3" in [s.strategy_id for s in eliminated]
    assert "s4" in [s.strategy_id for s in eliminated]

def test_weight_allocator_sum():
    """3. weight_allocator.py 权重分配 (验证 sum(weights) == 1.0)"""
    allocator = WeightAllocator()
    strategies = [
        RankedStrategy("s1", 80.0, 1, StrategyEvaluation(strategy_id="s1", total_score=80.0)),
        RankedStrategy("s2", 60.0, 2, StrategyEvaluation(strategy_id="s2", total_score=60.0)),
        RankedStrategy("s3", 40.0, 3, StrategyEvaluation(strategy_id="s3", total_score=40.0)),
    ]
    
    methods = ["equal", "rank_based", "score_based", "risk_parity"]
    for method in methods:
        weights = allocator.allocate_weights(strategies, method=method)
        # 验证所有权重和为 1.0 (允许微小浮点误差)
        assert abs(sum(weights.values()) - 1.0) < 1e-3, f"Failed for {method}"

def test_weighted_composer():
    """4. WeightedComposer 组合交易 (验证最终信号比例与权重匹配)"""
    composer = WeightedComposer(
        weights={"s1": 0.6, "s2": 0.4},
        threshold=0.5
    )
    
    df = pd.DataFrame(index=pd.date_range("2023-01-01", periods=3))
    
    # s1(0.6) + s2(0.4)
    # index 0: s1=1, s2=1   => sum = 1.0    => signal = 1 (>= 0.5)
    # index 1: s1=1, s2=-1  => sum = 0.2    => signal = 0 (-0.5 < x < 0.5)
    # index 2: s1=-1, s2=-1 => sum = -1.0   => signal = -1 (<= -0.5)
    atomic_signals = {
        "s1": pd.Series([1, 1, -1], index=df.index),
        "s2": pd.Series([1, -1, -1], index=df.index)
    }
    
    combined_signal = asyncio.run(composer.combine_signals(df, atomic_signals))
    
    assert combined_signal.iloc[0] == 1
    assert combined_signal.iloc[1] == 0
    assert combined_signal.iloc[2] == -1
