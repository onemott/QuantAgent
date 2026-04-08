import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

from main import app
from app.models.db_models import PerformanceMetric, StrategyEvaluation
from app.services.dynamic_selection.evaluator import StrategyEvaluator
from app.services.dynamic_selection.eliminator import StrategyEliminator, EliminationRule
from app.services.dynamic_selection.weight_allocator import WeightAllocator
from app.services.dynamic_selection.ranker import RankedStrategy

client = TestClient(app)

def test_evaluator_boundary_conditions():
    """1. Write a unit test to verify scoring boundary conditions in Evaluator"""
    evaluator = StrategyEvaluator()
    
    # Test extreme values
    perf = PerformanceMetric(
        annualized_return=0.25,  # > 0.2, should cap return score to 30.0
        max_drawdown_pct=0.35,   # > 0.3, should cap risk score to 0.0
        sharpe_ratio=2.5,        # > 2.0, should cap sharpe score to 25.0
        win_rate=0.8,            # 80%, stability score = 8.0
        total_trades=15          # >= 10, efficiency score = 10.0
    )
    
    # Use dummy dates for evaluate
    now = datetime.now(timezone.utc)
    
    scores = evaluator.calculate_scores(perf)
    
    assert scores["return_score"] == 30.0
    assert scores["risk_score"] == 0.0
    assert scores["risk_adjusted_score"] == 25.0
    assert scores["stability_score"] == 8.0
    assert scores["efficiency_score"] == 10.0
    assert scores["total_score"] == 73.0

def test_eliminator_logic_sequence():
    """2. Write an integration test for the elimination logic sequence in Eliminator"""
    eliminator = StrategyEliminator()
    rule = EliminationRule(
        min_score_threshold=40.0,
        elimination_ratio=0.2,
        min_consecutive_low=3,
        min_strategies=3
    )
    
    # Absolute low score (< 40) elimination
    strategies = [
        RankedStrategy("s1", 90.0, 1, StrategyEvaluation(strategy_id="s1", total_score=90.0)),
        RankedStrategy("s2", 80.0, 2, StrategyEvaluation(strategy_id="s2", total_score=80.0)),
        RankedStrategy("s3", 70.0, 3, StrategyEvaluation(strategy_id="s3", total_score=70.0)),
        RankedStrategy("s4", 50.0, 4, StrategyEvaluation(strategy_id="s4", total_score=50.0)),
        RankedStrategy("s5", 30.0, 5, StrategyEvaluation(strategy_id="s5", total_score=30.0)), # Should be eliminated by absolute threshold
    ]
    
    surviving, eliminated, reasons = eliminator.apply_elimination(strategies, rule)
    assert len(surviving) == 4
    assert len(eliminated) == 1
    assert eliminated[0].strategy_id == "s5"
    assert "absolute threshold" in reasons["s5"]

    # Bottom 20% relative elimination calculates correctly after absolute elimination
    strategies_rel = [
        RankedStrategy("s1", 90.0, 1, StrategyEvaluation(strategy_id="s1", total_score=90.0)),
        RankedStrategy("s2", 80.0, 2, StrategyEvaluation(strategy_id="s2", total_score=80.0)),
        RankedStrategy("s3", 70.0, 3, StrategyEvaluation(strategy_id="s3", total_score=70.0)),
        RankedStrategy("s4", 60.0, 4, StrategyEvaluation(strategy_id="s4", total_score=60.0)),
        RankedStrategy("s5", 50.0, 5, StrategyEvaluation(strategy_id="s5", total_score=50.0)),
    ]
    surviving_rel, eliminated_rel, reasons_rel = eliminator.apply_elimination(strategies_rel, rule)
    # 5 * 0.2 = 1 elimination
    assert len(surviving_rel) == 4
    assert len(eliminated_rel) == 1
    assert eliminated_rel[0].strategy_id == "s5"
    assert "relative ratio" in reasons_rel["s5"]
    
    # min_strategies = 3 fallback rule
    strategies_min = [
        RankedStrategy("s1", 35.0, 1, StrategyEvaluation(strategy_id="s1", total_score=35.0)),
        RankedStrategy("s2", 30.0, 2, StrategyEvaluation(strategy_id="s2", total_score=30.0)),
        RankedStrategy("s3", 25.0, 3, StrategyEvaluation(strategy_id="s3", total_score=25.0)),
        RankedStrategy("s4", 20.0, 4, StrategyEvaluation(strategy_id="s4", total_score=20.0)),
        RankedStrategy("s5", 15.0, 5, StrategyEvaluation(strategy_id="s5", total_score=15.0)),
    ]
    surviving_min, eliminated_min, reasons_min = eliminator.apply_elimination(strategies_min, rule)
    
    # All are < 40, so initially all 5 are eliminated.
    # But min_strategies=3 requires restoring the top 3 (s1, s2, s3).
    assert len(surviving_min) == 3
    assert len(eliminated_min) == 2
    
    surviving_ids = [s.strategy_id for s in surviving_min]
    assert "s1" in surviving_ids
    assert "s2" in surviving_ids
    assert "s3" in surviving_ids
    assert "s1" not in reasons_min
    assert "s2" not in reasons_min
    assert "s3" not in reasons_min

def test_weight_allocator_zero_division():
    """3. Write an integration test for zero division in WeightAllocator"""
    allocator = WeightAllocator()
    
    strategies = [
        RankedStrategy("s1", 80.0, 1, StrategyEvaluation(strategy_id="s1", volatility=0.0)),
        RankedStrategy("s2", 70.0, 2, StrategyEvaluation(strategy_id="s2", volatility=0.0)),
    ]
    
    weights = allocator.allocate_weights(strategies, method="risk_parity")
    
    # Both have volatility 0.0 -> replaced by 0.01 internally
    # So their weights should be equal (0.5 each)
    assert "s1" in weights
    assert "s2" in weights
    assert weights["s1"] == 0.5
    assert weights["s2"] == 0.5

def test_api_boundary_and_response_format():
    """4. API Boundary and Response Format Test"""
    # config test
    response_config = client.get("/api/v1/dynamic-selection/config")
    assert response_config.status_code == 200
    config_data = response_config.json()
    assert "evaluation_interval" in config_data
    assert "metrics_weights" in config_data
    assert "elimination_threshold" in config_data
    assert "max_strategies" in config_data
    assert "min_strategies" in config_data

    # update config test
    new_config = {
        "evaluation_interval": "1m",
        "metrics_weights": {
            "return_score": 0.4,
            "risk_score": 0.2,
            "stability_score": 0.2,
            "efficiency_score": 0.2
        },
        "elimination_threshold": 0.4,
        "max_strategies": 5,
        "min_strategies": 2
    }
    response_update = client.post("/api/v1/dynamic-selection/config", json=new_config)
    assert response_update.status_code == 200
    update_data = response_update.json()
    assert update_data["evaluation_interval"] == "1m"
    assert update_data["max_strategies"] == 5

    # update allocation test
    allocation_payload = {
        "strategy_weights": {
            "s1": 0.6,
            "s2": 0.4
        }
    }
    response_alloc = client.post("/api/v1/dynamic-selection/allocation", json=allocation_payload)
    assert response_alloc.status_code == 200
    alloc_data = response_alloc.json()
    assert alloc_data["status"] == "success"
    assert alloc_data["weights"]["s1"] == 0.6
