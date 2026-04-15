import pytest
import pandas as pd
import numpy as np
from datetime import timedelta

from app.services.backtester.annualization import infer_annualization_factor
from app.services.walk_forward.window_manager import WindowManager
from app.services.walk_forward.stability_analyzer import StabilityAnalyzer
from app.services.walk_forward.optimizer import WalkForwardOptimizer

def test_window_manager_tail_handling_index():
    # 100 samples
    dates = pd.date_range("2020-01-01", periods=100)
    
    # method='rolling', train_size=60, test_size=20, step_size=20
    wm = WindowManager(method='rolling', train_size=60, test_size=20, step_size=20)
    windows = wm.generate_windows(dates)
    
    # Start: 0
    # Window 1: train 0-59, test 60-79 (valid)
    # Window 2: train 20-79, test 80-99 (valid)
    # Window 3: train 40-99, test 100-119 (invalid, end_idx > 100)
    assert len(windows) == 2
    # test 80-99 means test_start is index 80, test_end is index 99
    assert windows[-1]['test'][1] == dates[99]

def test_window_manager_tail_handling_time():
    # 101 periods gives a total span of 100 days (from day 0 to day 100)
    dates = pd.date_range("2020-01-01", periods=101, freq='D')
    
    # train 60 days, test 20 days, step 20 days
    wm = WindowManager(method='rolling', train_size=timedelta(days=60), test_size=timedelta(days=20), step_size=timedelta(days=20))
    windows = wm.generate_windows(dates)
    
    # Last test window must not exceed 100 days
    # window 1: train 2020-01-01 to 2020-03-01 (60 days), test 2020-03-01 to 2020-03-21 (20 days)
    # window 2: train 2020-01-21 to 2020-03-21 (60 days), test 2020-03-21 to 2020-04-10 (20 days) -> Total days from 2020-01-01 is 100
    assert len(windows) == 2
    assert windows[-1]['test'][1] <= dates[-1]

def test_window_manager_rejects_non_positive_step_size():
    with pytest.raises(ValueError, match="step_size must be > 0"):
        WindowManager(method='rolling', train_size=60, test_size=20, step_size=0)

    with pytest.raises(ValueError, match="test_size must be > 0"):
        WindowManager(method='rolling', train_size=60, test_size=0, step_size=20)

def test_stability_analyzer_wfe_negative_or_zero_is():
    # IS return is exactly 0
    is_rets = pd.Series([0.0] * 10)
    oos_rets = pd.Series([0.01] * 10)
    wfe = StabilityAnalyzer.calculate_wfe(is_rets, oos_rets)
    assert wfe == 0.0
    
    # IS return is slightly negative
    is_rets_neg = pd.Series([-0.01] * 10)
    oos_rets_pos = pd.Series([0.01] * 10)
    wfe_neg = StabilityAnalyzer.calculate_wfe(is_rets_neg, oos_rets_pos)
    expected_wfe = (
        StabilityAnalyzer._annualized_return(oos_rets_pos, 252)
        / StabilityAnalyzer._annualized_return(is_rets_neg, 252)
    )
    assert wfe_neg == pytest.approx(expected_wfe)
    assert wfe_neg < 0

def test_stability_analyzer_wfe_logs_warning_for_outliers(caplog):
    is_rets = pd.Series([0.001] * 20)
    oos_rets = pd.Series([0.01] * 20)

    with caplog.at_level("WARNING"):
        wfe = StabilityAnalyzer.calculate_wfe(is_rets, oos_rets)

    assert wfe > StabilityAnalyzer.WFE_UPPER_BOUND
    assert "outside the expected range" in caplog.text

def test_walk_forward_optimizer_annual_return_uses_decimal_units():
    visible_index = pd.date_range("2024-01-01", periods=3, freq="D")
    raw_performance = {
        "equity_curve": [100.0, 110.0, 121.0],
        "returns": [0.0, 0.1, 0.1],
        "trade_markers": [0.0, 1.0, 0.0],
        "final_position": 1.0,
    }

    result = WalkForwardOptimizer._build_visible_oos_performance(
        raw_performance=raw_performance,
        visible_offset=0,
        initial_capital=100.0,
        visible_index=visible_index,
        annualization_factor=252,
    )

    expected_annual_return = StabilityAnalyzer._annualized_return(
        pd.Series(raw_performance["returns"], index=visible_index, dtype=float),
        infer_annualization_factor(visible_index),
    )
    assert result["annual_return"] == pytest.approx(expected_annual_return)
    assert result["annual_return"] < 100

def test_walk_forward_optimizer_resolve_stitched_slice_handles_overlap():
    stitched_slice = WalkForwardOptimizer._resolve_stitched_slice(
        test_start_idx=80,
        test_end_idx=109,
        last_stitched_end_idx=89,
    )

    assert stitched_slice == (89, 1)

def test_walk_forward_optimizer_infers_initial_position_from_sparse_signal_history():
    signals = pd.Series([1.0, 0.0, 0.0, -1.0, 0.0], index=pd.date_range("2024-01-01", periods=5, freq="D"))

    initial_position = WalkForwardOptimizer._infer_initial_position(signals, start_idx=3)

    assert initial_position == pytest.approx(1.0)

def test_stability_analyzer_window_parameter_stability():
    optimal_params = [
        {"fast": 10, "slow": 20},
        {"fast": 10, "slow": 22},
        {"fast": 14, "slow": 30},
    ]

    scores = StabilityAnalyzer.calculate_window_parameter_stability(optimal_params)

    assert len(scores) == 3
    assert scores[0] == pytest.approx(1.0)
    assert 0.0 <= scores[1] <= 1.0
    assert 0.0 <= scores[2] <= 1.0

def test_stability_analyzer_param_stability():
    # Stable params
    stable_params = [{'period': 10}, {'period': 11}, {'period': 10}]
    score_stable = StabilityAnalyzer.calculate_parameter_stability(stable_params)
    assert score_stable['period'] > 0.8  # Should be near 1.0

    # Jumping params
    jumping_params = [{'period': 10}, {'period': 50}, {'period': 5}]
    score_jumping = StabilityAnalyzer.calculate_parameter_stability(jumping_params)
    assert score_jumping['period'] < 0.2  # Should be near 0
