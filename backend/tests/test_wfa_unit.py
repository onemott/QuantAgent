import pytest
import pandas as pd
import numpy as np
from datetime import timedelta
from app.services.walk_forward.window_manager import WindowManager
from app.services.walk_forward.stability_analyzer import StabilityAnalyzer

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
    assert wfe_neg == 0.0

def test_stability_analyzer_param_stability():
    # Stable params
    stable_params = [{'period': 10}, {'period': 11}, {'period': 10}]
    score_stable = StabilityAnalyzer.calculate_parameter_stability(stable_params)
    assert score_stable['period'] > 0.8  # Should be near 1.0

    # Jumping params
    jumping_params = [{'period': 10}, {'period': 50}, {'period': 5}]
    score_jumping = StabilityAnalyzer.calculate_parameter_stability(jumping_params)
    assert score_jumping['period'] < 0.2  # Should be near 0
