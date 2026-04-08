import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
from app.services.walk_forward.optimizer import WalkForwardOptimizer

# --- Fixtures ---
@pytest.fixture
def sample_kline_data():
    """Construct virtual K-line data with clear up/down trends."""
    dates = pd.date_range(start="2023-01-01", periods=300, freq="D")
    
    # Create a trend: up for first 150 days, down for next 150 days
    close_prices = np.concatenate([
        np.linspace(100, 200, 150),
        np.linspace(200, 100, 150)
    ])
    
    # Add some noise
    np.random.seed(42)
    noise = np.random.normal(0, 2, 300)
    close_prices += noise
    
    df = pd.DataFrame({
        "open": close_prices - 1,
        "high": close_prices + 2,
        "low": close_prices - 2,
        "close": close_prices,
        "volume": np.random.randint(100, 1000, size=300)
    }, index=dates)
    
    return df

@pytest.fixture
def small_kline_data():
    """Construct small dataset for boundary condition testing."""
    dates = pd.date_range(start="2023-01-01", periods=100, freq="D")
    close_prices = np.linspace(100, 150, 100)
    
    df = pd.DataFrame({
        "open": close_prices - 1,
        "high": close_prices + 2,
        "low": close_prices - 2,
        "close": close_prices,
        "volume": 100
    }, index=dates)
    
    return df

# --- Tests ---

@pytest.mark.asyncio
async def test_wfa_stability_and_wfe(sample_kline_data):
    """
    1. Construct virtual K-line data with up/down trends, run Walk-Forward process, verify is_wfe_stable output.
    """
    optimizer = WalkForwardOptimizer(sample_kline_data, strategy_type="ma", initial_capital=10000.0)
    
    # Run WFO with fast params to speed up test
    result = await optimizer.run_wfo(
        is_days=60,
        oos_days=30,
        n_trials=5,  # Small number of trials for testing
        use_numba=False,
        embargo_days=0
    )
    
    assert "error" not in result
    assert "stability_analysis" in result
    
    stability = result["stability_analysis"]
    assert "is_wfe_stable" in stability
    assert isinstance(stability["is_wfe_stable"], bool)
    assert "wfe_per_window" in stability
    assert len(stability["wfe_per_window"]) == len(result["walk_forward_results"])


@pytest.mark.asyncio
async def test_wfa_boundary_conditions(small_kline_data):
    """
    2. Boundary conditions: pass small dataframe to run_wfo, check generation of single/few IS/OOS splits and head/tail truncation.
    """
    optimizer = WalkForwardOptimizer(small_kline_data, strategy_type="ma", initial_capital=10000.0)
    
    result = await optimizer.run_wfo(
        is_days=60,
        oos_days=30,
        n_trials=2,
        use_numba=False,
        embargo_days=0
    )
    
    assert "error" not in result
    
    # Data is 100 days.
    # IS = 60 days, OOS = 30 days, Step = 30 days.
    # Window 1: IS [0:60], OOS [60:90] -> total 90 days. Valid.
    # Window 2: IS [30:90], OOS [90:120] -> OOS would be truncated to [90:100], which is 10 days. 
    # Let's check how many windows are generated and if they are valid.
    windows = result["walk_forward_results"]
    assert len(windows) > 0
    
    for w in windows:
        is_start = pd.to_datetime(w["is_period"][0])
        is_end = pd.to_datetime(w["is_period"][1])
        oos_start = pd.to_datetime(w["oos_period"][0])
        oos_end = pd.to_datetime(w["oos_period"][1])
        
        # Ensure dates are within the dataframe
        assert is_start >= small_kline_data.index[0]
        assert oos_end <= small_kline_data.index[-1]
        
        # Ensure OOS comes after IS
        assert oos_start > is_start


@pytest.mark.asyncio
async def test_wfa_fund_continuity(sample_kline_data):
    """
    3. Fund continuity: Check stitched_oos_performance equity curve at OOS transition dates for unnatural jumps/flat spots to ensure day 1 returns are correct.
    """
    optimizer = WalkForwardOptimizer(sample_kline_data, strategy_type="ma", initial_capital=10000.0)
    
    result = await optimizer.run_wfo(
        is_days=60,
        oos_days=30,
        n_trials=2,
        use_numba=False,
        embargo_days=0
    )
    
    assert "stitched_oos_performance" in result
    stitched = result["stitched_oos_performance"]
    
    equity_curve = stitched.get("equity_curve", [])
    dates = stitched.get("dates", [])
    
    assert len(equity_curve) > 0
    assert len(equity_curve) == len(dates)
    
    # Check for unnatural jumps. We expect the equity curve to be continuous.
    # We shouldn't see massive 50% jumps in a single day for a simple MA strategy on this data.
    if len(equity_curve) > 1:
        equity_series = pd.Series(equity_curve)
        pct_change = equity_series.pct_change().dropna()
        
        # Assuming max daily jump shouldn't exceed 20% in this mock data
        max_jump = pct_change.abs().max()
        assert max_jump < 0.20, f"Unnatural jump detected: {max_jump*100}%"


@pytest.mark.asyncio
async def test_wfa_metric_consistency(sample_kline_data):
    """
    4. Metric consistency: Ensure stability_analysis.parameter_stability_scores is valid JSON containing floats, no serialization errors.
    """
    optimizer = WalkForwardOptimizer(sample_kline_data, strategy_type="ma", initial_capital=10000.0)
    
    result = await optimizer.run_wfo(
        is_days=60,
        oos_days=30,
        n_trials=2,
        use_numba=False,
        embargo_days=0
    )
    
    stability = result.get("stability_analysis", {})
    scores = stability.get("parameter_stability_scores", {})
    
    # Ensure it's a dict and values are standard floats, not numpy types
    assert isinstance(scores, dict)
    
    for key, val in scores.items():
        assert isinstance(key, str)
        # Check if val is exactly Python float (or int, which is serializable)
        assert type(val) in (float, int), f"Value {val} for key {key} is of type {type(val)}, not float"
        
    # Test JSON serialization directly
    try:
        json_str = json.dumps(scores)
        assert isinstance(json_str, str)
    except TypeError as e:
        pytest.fail(f"Serialization failed: {e}")
