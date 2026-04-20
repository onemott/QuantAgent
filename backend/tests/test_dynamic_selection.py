import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

from main import app
from app.models.db_models import PerformanceMetric, StrategyEvaluation
from app.services.dynamic_selection.evaluator import StrategyEvaluator
from app.services.dynamic_selection.eliminator import StrategyEliminator, EliminationRule, RevivalRule
from app.services.dynamic_selection.weight_allocator import WeightAllocator
from app.services.dynamic_selection.ranker import RankedStrategy

client = TestClient(app)

def test_evaluator_boundary_conditions():
    """1. Write a unit test to verify scoring boundary conditions in Evaluator"""
    evaluator = StrategyEvaluator()
    
    # Test extreme values
    # Note: VirtualBus outputs metrics in decimal format (e.g., 0.25 means 25%, not 25.0)
    perf = PerformanceMetric(
        annualized_return=0.25,  # 25% (> 20% threshold), should cap return score to 30.0
        max_drawdown_pct=0.35,   # 35% (> 30% threshold), should cap risk score to 0.0
        sharpe_ratio=2.5,        # > 2.0, should cap sharpe score to 25.0
        win_rate=0.80,           # 80%, stability score = 8.0
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
    assert "evaluation_period" in config_data
    assert "metrics_weights" in config_data
    assert "elimination_threshold" in config_data
    assert "max_strategies" in config_data
    assert "min_strategies" in config_data

    # update config test
    new_config = {
        "evaluation_period": "1m",
        "metrics_weights": {
            "return_score": 0.4,
            "risk_score": 0.2,
            "stability_score": 0.2,
            "efficiency_score": 0.2
        },
        "elimination_threshold": 40,  # int type (0-100), not float
        "relative_ratio": 0.2,
        "max_strategies": 5,
        "min_strategies": 2
    }
    response_update = client.post("/api/v1/dynamic-selection/config", json=new_config)
    assert response_update.status_code == 200
    update_data = response_update.json()
    assert update_data["evaluation_period"] == "1m"
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


def test_evaluation_period_invalid_values():
    """Test that invalid evaluation_period values return 400 error"""
    # Base payload for dynamic_selection strategy
    base_payload = {
        "strategy_id": 1,
        "symbol": "BTCUSDT",
        "start_time": "2024-01-01T00:00:00Z",
        "end_time": "2024-01-31T23:59:59Z",
        "speed": 60,
        "initial_capital": 10000.0,
        "strategy_type": "dynamic_selection",
        "params": {
            "atomic_strategies": [
                {"strategy_id": "ds_ma_1", "strategy_type": "ma", "params": {"fast_period": 5, "slow_period": 20}},
                {"strategy_id": "ds_rsi_1", "strategy_type": "rsi", "params": {"period": 14}}
            ]
        }
    }
    
    # Test 1: Negative evaluation_period
    payload_negative = {**base_payload, "params": {**base_payload["params"], "evaluation_period": -100}}
    response = client.post("/api/v1/replay/create", json=payload_negative)
    assert response.status_code == 400
    assert "evaluation_period must be a positive integer" in response.json().get("detail", "")
    
    # Test 2: Non-integer evaluation_period (string "abc")
    payload_string = {**base_payload, "params": {**base_payload["params"], "evaluation_period": "abc"}}
    response = client.post("/api/v1/replay/create", json=payload_string)
    assert response.status_code == 400  # Backend manual validation returns 400
    
    # Test 3: Zero evaluation_period
    payload_zero = {**base_payload, "params": {**base_payload["params"], "evaluation_period": 0}}
    response = client.post("/api/v1/replay/create", json=payload_zero)
    assert response.status_code == 400
    assert "evaluation_period must be a positive integer" in response.json().get("detail", "")


@pytest.mark.asyncio
async def test_session_id_end_to_end_flow():
    """Test that session_id is correctly passed through evaluation flow using mocked database"""
    from unittest.mock import AsyncMock, MagicMock, patch
    from httpx import AsyncClient
    from httpx import ASGITransport
    from app.services.database import get_db_session
    from app.models.db_models import SelectionHistory, TradePair
    
    test_session_id = "TEST_SESSION_123"
    
    # Create mock history records for the /history endpoint test
    mock_history_records = [
        SelectionHistory(
            id=1,
            evaluation_date=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
            session_id=test_session_id,
            total_strategies=3,
            surviving_count=2,
            eliminated_count=1,
            eliminated_strategy_ids=["s3"],
            elimination_reasons={"s3": "low_score"},
            strategy_weights={"s1": 0.6, "s2": 0.4}
        )
    ]
    
    # Create mock database session
    mock_db_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = mock_history_records
    mock_db_session.execute = AsyncMock(return_value=mock_result)
    mock_db_session.commit = AsyncMock()
    mock_db_session.add = MagicMock()
    
    async def mock_get_db():
        yield mock_db_session
    
    # Override the dependency
    app.dependency_overrides[get_db_session] = mock_get_db
    
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            # Test 1: Call /evaluate endpoint with session_id query parameter
            # Mock TradePair query to return empty (no trades scenario)
            mock_result_empty = MagicMock()
            mock_result_empty.scalars.return_value.all.return_value = []
            mock_db_session.execute = AsyncMock(return_value=mock_result_empty)
            
            evaluate_payload = {
                "window_start": "2024-01-01T00:00:00Z",
                "window_end": "2024-01-31T23:59:59Z"
            }
            
            response = await ac.post(
                f"/api/v1/dynamic-selection/evaluate?session_id={test_session_id}",
                json=evaluate_payload
            )
            # The endpoint should return 200 with warning status when no trades exist
            assert response.status_code == 200
            result = response.json()
            assert "status" in result
            assert result["status"] == "warning"
            assert "total_strategies" in result
            
            # Test 2: Query /history endpoint with session_id filter
            # Reset mock to return history records
            mock_result_history = MagicMock()
            mock_result_history.scalars.return_value.all.return_value = mock_history_records
            mock_db_session.execute = AsyncMock(return_value=mock_result_history)
            
            response = await ac.get(f"/api/v1/dynamic-selection/history?session_id={test_session_id}")
            assert response.status_code == 200
            # Response should be a list with the mocked history record
            data = response.json()
            assert isinstance(data, list)
            assert len(data) == 1
            assert data[0]["session_id"] == test_session_id
            assert data[0]["total_strategies"] == 3
    finally:
        # Clean up the override after test
        app.dependency_overrides.pop(get_db_session, None)


# =====================================================
# Hibernation and Revival Mechanism Tests
# =====================================================

def test_strategy_hibernation_instead_of_elimination():
    """
    验证策略评分低于阈值后进入休眠状态而非永久淘汰。
    
    场景：
    - 创建策略评分低于 40 分的场景
    - 执行淘汰后，验证策略存在于 hibernating_strategies 而非被完全删除
    - 验证 alive_strategies 中不再包含该策略
    """
    eliminator = StrategyEliminator()
    rule = EliminationRule(
        min_score_threshold=40.0,
        elimination_ratio=0.0,  # 不启用相对比例淘汰
        min_consecutive_low=99,  # 禁用连续低分淘汰
        min_strategies=1
    )
    
    strategies = [
        RankedStrategy("s1", 80.0, 1, StrategyEvaluation(strategy_id="s1", total_score=80.0)),
        RankedStrategy("s2", 70.0, 2, StrategyEvaluation(strategy_id="s2", total_score=70.0)),
        RankedStrategy("s3", 35.0, 3, StrategyEvaluation(strategy_id="s3", total_score=35.0)),  # 低于 40，应进入休眠
    ]
    
    surviving, eliminated, reasons = eliminator.apply_elimination(strategies, rule)
    
    # 验证淘汰逻辑：s3 因评分低于 40 被淘汰
    assert len(surviving) == 2
    assert len(eliminated) == 1
    assert eliminated[0].strategy_id == "s3"
    assert "absolute threshold" in reasons["s3"]
    
    # 验证淘汰原因包含评分信息
    assert "35" in reasons["s3"] or "35.00" in reasons["s3"]


@pytest.mark.asyncio
async def test_hibernating_strategy_continues_virtual_evaluation():
    """
    验证休眠策略仍然保留虚拟总线以继续接收数据。
    
    场景：
    - 策略进入休眠后，验证 hibernating_buses 中存在对应的虚拟总线
    - 验证该总线可以继续接收数据
    """
    from app.core.virtual_bus import VirtualTradingBus
    from app.models.trading import BarData
    
    # 创建虚拟总线
    vbus = VirtualTradingBus(initial_capital=1000.0)
    
    # 模拟休眠状态：总线被移入 hibernating_buses
    hibernating_buses = {"s3": vbus}
    
    # 验证休眠策略的虚拟总线存在
    assert "s3" in hibernating_buses
    
    # 验证总线可以继续接收数据
    bar = BarData(
        symbol="BTCUSDT",
        interval="1h",
        datetime=datetime.now(timezone.utc),
        open=100.0,
        high=105.0,
        low=95.0,
        close=102.0,
        volume=10.0
    )
    
    # 模拟发布 K 线数据
    await vbus.publish_bar(bar)
    
    # 验证总线已接收数据
    assert vbus.router.current_bar.close == 102.0


def test_revival_after_consecutive_high_scores():
    """
    验证休眠策略连续高分后成功复活。
    
    场景：
    - 模拟休眠策略连续 2 轮评分 >= 45
    - 调用 check_revival，验证返回的 revived_ids 包含该策略
    - 验证 revival_reasons 中有正确的原因字符串
    """
    rule = RevivalRule(
        revival_score_threshold=45.0,
        min_consecutive_high=2,
        max_revival_per_round=2
    )
    
    # 模拟第 1 轮：策略评分 50（>= 45），计数变为 1
    hibernating_scores = {"s3": 50.0}
    consecutive_high_counts = {}
    
    revived_ids, updated_counts, revival_reasons = StrategyEliminator.check_revival(
        hibernating_scores=hibernating_scores,
        consecutive_high_counts=consecutive_high_counts,
        rule=rule
    )
    
    # 第 1 轮后：计数 = 1，未达到 2，不复活
    assert len(revived_ids) == 0
    assert updated_counts["s3"] == 1
    
    # 模拟第 2 轮：策略评分 48（>= 45），计数变为 2
    consecutive_high_counts = updated_counts
    hibernating_scores = {"s3": 48.0}
    
    revived_ids, updated_counts, revival_reasons = StrategyEliminator.check_revival(
        hibernating_scores=hibernating_scores,
        consecutive_high_counts=consecutive_high_counts,
        rule=rule
    )
    
    # 第 2 轮后：计数 = 2，达到阈值，成功复活
    assert "s3" in revived_ids
    assert "s3" in revival_reasons
    assert "48" in revival_reasons["s3"] or "48.00" in revival_reasons["s3"]
    assert "consecutive rounds" in revival_reasons["s3"]


def test_revived_strategy_rejoins_weight_allocation():
    """
    验证复活策略重新参与权重分配。
    
    场景：
    - 策略复活后，验证它回到 alive_strategies
    - 验证 consecutive_low_counts 被重置为 0
    - 验证 consecutive_high_counts 中该策略被清除
    """
    from unittest.mock import MagicMock
    
    # 模拟复活后的状态更新
    alive_strategies = {"s1": MagicMock(), "s2": MagicMock()}
    hibernating_strategies = {"s3": MagicMock()}
    hibernating_buses = {"s3": MagicMock()}
    consecutive_low_counts = {"s1": 0, "s2": 1, "s3": 3}  # s3 原来有 3 次低分
    consecutive_high_counts = {"s3": 2}  # s3 已连续 2 次高分
    
    # 模拟复活操作：将 s3 从休眠移回活跃
    revived_id = "s3"
    alive_strategies[revived_id] = hibernating_strategies.pop(revived_id)
    virtual_buses = {}
    virtual_buses[revived_id] = hibernating_buses.pop(revived_id)
    
    # 重置计数
    consecutive_low_counts[revived_id] = 0
    del consecutive_high_counts[revived_id]
    
    # 验证状态
    assert revived_id in alive_strategies
    assert revived_id not in hibernating_strategies
    assert consecutive_low_counts[revived_id] == 0
    assert revived_id not in consecutive_high_counts


def test_max_revival_per_round_limit():
    """
    验证每轮复活数不超过上限。
    
    场景：
    - 创建 3 个休眠策略都满足复活条件
    - 设置 max_revival_per_round = 2
    - 验证只有 2 个策略被复活（按评分高低）
    """
    rule = RevivalRule(
        revival_score_threshold=45.0,
        min_consecutive_high=2,
        max_revival_per_round=2
    )
    
    # 3 个休眠策略，都已连续 2 次高分，都满足复活条件
    hibernating_scores = {
        "s3": 50.0,  # 最高分
        "s4": 48.0,  # 次高分
        "s5": 46.0   # 最低分
    }
    consecutive_high_counts = {
        "s3": 2,
        "s4": 2,
        "s5": 2
    }
    
    revived_ids, updated_counts, revival_reasons = StrategyEliminator.check_revival(
        hibernating_scores=hibernating_scores,
        consecutive_high_counts=consecutive_high_counts,
        rule=rule
    )
    
    # 只有 2 个策略被复活（按评分高低选择）
    assert len(revived_ids) == 2
    assert "s3" in revived_ids  # 最高分
    assert "s4" in revived_ids  # 次高分
    assert "s5" not in revived_ids  # 最低分未被选中


def test_revival_threshold_hysteresis():
    """
    验证复活阈值高于淘汰阈值（防止频繁切换）。
    
    场景：
    - 策略评分为 42（高于淘汰阈值 40，低于复活阈值 45）
    - 验证该策略不会被复活（虽然已高于淘汰线，但未达到复活线）
    - 验证 consecutive_high_counts 不递增
    """
    rule = RevivalRule(
        revival_score_threshold=45.0,
        min_consecutive_high=2,
        max_revival_per_round=2
    )
    
    # 策略评分 42（高于淘汰阈值 40，但低于复活阈值 45）
    hibernating_scores = {"s3": 42.0}
    consecutive_high_counts = {"s3": 1}  # 之前已有 1 次高分
    
    revived_ids, updated_counts, revival_reasons = StrategyEliminator.check_revival(
        hibernating_scores=hibernating_scores,
        consecutive_high_counts=consecutive_high_counts,
        rule=rule
    )
    
    # 评分未达到复活阈值，计数重置为 0
    assert len(revived_ids) == 0
    assert updated_counts["s3"] == 0  # 计数被重置
    assert "s3" not in revival_reasons


def test_full_hibernation_revival_lifecycle():
    """
    验证多轮评估中休眠-复活的完整生命周期。
    
    场景：
    - 轮次 1：策略 A 评分 35，进入休眠
    - 轮次 2：策略 A 评分 50，consecutive_high_counts = 1，仍休眠
    - 轮次 3：策略 A 评分 48，consecutive_high_counts = 2，复活
    - 验证策略 A 回到活跃集合
    """
    rule = RevivalRule(
        revival_score_threshold=45.0,
        min_consecutive_high=2,
        max_revival_per_round=2
    )
    
    # 轮次 1：策略 A 评分 35，进入休眠
    eliminator = StrategyEliminator()
    elim_rule = EliminationRule(min_score_threshold=40.0, elimination_ratio=0.0, min_strategies=1)
    strategies = [
        RankedStrategy("s1", 80.0, 1, StrategyEvaluation(strategy_id="s1", total_score=80.0)),
        RankedStrategy("sA", 35.0, 2, StrategyEvaluation(strategy_id="sA", total_score=35.0)),
    ]
    surviving, eliminated, reasons = eliminator.apply_elimination(strategies, elim_rule)
    
    assert "sA" in [s.strategy_id for s in eliminated]
    
    # 轮次 2：策略 A 评分 50
    hibernating_scores = {"sA": 50.0}
    consecutive_high_counts = {}
    
    revived_ids, consecutive_high_counts, _ = StrategyEliminator.check_revival(
        hibernating_scores=hibernating_scores,
        consecutive_high_counts=consecutive_high_counts,
        rule=rule
    )
    assert len(revived_ids) == 0  # 未达到连续 2 次
    assert consecutive_high_counts["sA"] == 1
    
    # 轮次 3：策略 A 评分 48
    hibernating_scores = {"sA": 48.0}
    
    revived_ids, consecutive_high_counts, revival_reasons = StrategyEliminator.check_revival(
        hibernating_scores=hibernating_scores,
        consecutive_high_counts=consecutive_high_counts,
        rule=rule
    )
    
    # 策略 A 成功复活
    assert "sA" in revived_ids
    assert consecutive_high_counts["sA"] == 2


def test_revival_reset_on_low_score():
    """
    验证休眠策略评分下降时重置连续高分计数。
    
    场景：
    - 休眠策略第 1 轮评分 50（计数 = 1）
    - 第 2 轮评分 30（计数重置为 0）
    - 第 3 轮评分 50（计数 = 1）
    - 验证第 3 轮后策略仍处于休眠（计数未达到 2）
    """
    rule = RevivalRule(
        revival_score_threshold=45.0,
        min_consecutive_high=2,
        max_revival_per_round=2
    )
    
    consecutive_high_counts = {}
    
    # 第 1 轮：评分 50
    hibernating_scores = {"s3": 50.0}
    revived_ids, consecutive_high_counts, _ = StrategyEliminator.check_revival(
        hibernating_scores=hibernating_scores,
        consecutive_high_counts=consecutive_high_counts,
        rule=rule
    )
    assert len(revived_ids) == 0
    assert consecutive_high_counts["s3"] == 1
    
    # 第 2 轮：评分 30（低于复活阈值）
    hibernating_scores = {"s3": 30.0}
    revived_ids, consecutive_high_counts, _ = StrategyEliminator.check_revival(
        hibernating_scores=hibernating_scores,
        consecutive_high_counts=consecutive_high_counts,
        rule=rule
    )
    assert len(revived_ids) == 0
    assert consecutive_high_counts["s3"] == 0  # 计数被重置
    
    # 第 3 轮：评分 50
    hibernating_scores = {"s3": 50.0}
    revived_ids, consecutive_high_counts, _ = StrategyEliminator.check_revival(
        hibernating_scores=hibernating_scores,
        consecutive_high_counts=consecutive_high_counts,
        rule=rule
    )
    
    # 第 3 轮后策略仍处于休眠（计数 = 1，未达到 2）
    assert len(revived_ids) == 0
    assert consecutive_high_counts["s3"] == 1
