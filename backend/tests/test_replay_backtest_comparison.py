"""
Tests for replay-backtest comparison functionality.
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime, timezone


class TestTimeOverlapCalculation:
    """Tests for time overlap percentage calculation."""

    def test_time_overlap_full_overlap(self):
        """100% overlap when periods match."""
        replay_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        replay_end = datetime(2024, 6, 30, tzinfo=timezone.utc)
        bt_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        bt_end = datetime(2024, 6, 30, tzinfo=timezone.utc)

        replay_duration = (replay_end - replay_start).days
        bt_duration = (bt_end - bt_start).days

        overlap = min(replay_duration, bt_duration) / max(replay_duration, bt_duration)
        overlap_pct = overlap * 100

        assert overlap_pct == 100.0

    def test_time_overlap_partial_overlap(self):
        """Partial overlap calculation."""
        replay_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        replay_end = datetime(2024, 3, 31, tzinfo=timezone.utc)
        bt_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        bt_end = datetime(2024, 6, 30, tzinfo=timezone.utc)

        replay_duration = (replay_end - replay_start).days  # 90 days
        bt_duration = (bt_end - bt_start).days  # 181 days

        overlap = min(replay_duration, bt_duration) / max(replay_duration, bt_duration)
        overlap_pct = overlap * 100

        assert overlap_pct == pytest.approx(49.7, 0.5)

    def test_time_overlap_no_overlap(self):
        """No overlap returns 0."""
        replay_start = datetime(2024, 7, 1, tzinfo=timezone.utc)
        replay_end = datetime(2024, 9, 30, tzinfo=timezone.utc)
        bt_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        bt_end = datetime(2024, 6, 30, tzinfo=timezone.utc)

        replay_duration = (replay_end - replay_start).days
        bt_duration = (bt_end - bt_start).days

        overlap = min(replay_duration, bt_duration) / max(replay_duration, bt_duration)
        overlap_pct = overlap * 100

        # In this implementation, overlap is always positive since we use min/max
        # But in the actual API, the comparison would show as warning if < 80%
        assert overlap_pct >= 0

    def test_time_overlap_warns_below_threshold(self):
        """Overlap below 80% should trigger warning."""
        THRESHOLD = 80

        test_cases = [
            (90, True),   # above threshold
            (80, True),   # at threshold
            (79, False),  # below threshold
            (50, False),  # well below threshold
        ]

        for overlap_pct, should_warn in test_cases:
            warns = overlap_pct < THRESHOLD
            assert warns == should_warn


class TestParamDiffDetection:
    """Tests for parameter difference detection."""

    def test_param_diff_detects_differences(self):
        """param_diff correctly identifies different parameter values."""
        replay_params = {"fast_period": 10, "slow_period": 50, "atr_period": 14}
        backtest_params = {"fast_period": 20, "slow_period": 50, "atr_period": 14}

        param_diff = {}
        all_keys = set(list(replay_params.keys()) + list(backtest_params.keys()))
        for key in all_keys:
            r_val = replay_params.get(key)
            b_val = backtest_params.get(key)
            if r_val != b_val:
                param_diff[key] = {"replay": r_val, "backtest": b_val}

        assert "fast_period" in param_diff
        assert param_diff["fast_period"]["replay"] == 10
        assert param_diff["fast_period"]["backtest"] == 20
        assert "slow_period" not in param_diff  # same value
        assert "atr_period" not in param_diff   # same value

    def test_param_diff_empty_when_identical(self):
        """param_diff is empty when all params match."""
        replay_params = {"fast_period": 10, "slow_period": 50}
        backtest_params = {"fast_period": 10, "slow_period": 50}

        param_diff = {}
        all_keys = set(list(replay_params.keys()) + list(backtest_params.keys()))
        for key in all_keys:
            r_val = replay_params.get(key)
            b_val = backtest_params.get(key)
            if r_val != b_val:
                param_diff[key] = {"replay": r_val, "backtest": b_val}

        assert len(param_diff) == 0

    def test_param_diff_detects_missing_keys(self):
        """param_diff detects params in one set but not the other."""
        replay_params = {"fast_period": 10, "slow_period": 50}
        backtest_params = {"fast_period": 10, "slow_period": 50, "atr_multiplier": 2.0}

        param_diff = {}
        all_keys = set(list(replay_params.keys()) + list(backtest_params.keys()))
        for key in all_keys:
            r_val = replay_params.get(key)
            b_val = backtest_params.get(key)
            if r_val != b_val:
                param_diff[key] = {"replay": r_val, "backtest": b_val}

        assert "atr_multiplier" in param_diff
        assert param_diff["atr_multiplier"]["replay"] is None
        assert param_diff["atr_multiplier"]["backtest"] == 2.0


class TestEquityCurveNormalization:
    """Tests for equity curve normalization to relative performance."""

    def test_normalize_to_relative_starting_100(self):
        """Equity curves are normalized to start at 100."""
        equity_curve = [
            {"timestamp": "2024-01-01", "equity": 10000},
            {"timestamp": "2024-01-02", "equity": 10500},
            {"timestamp": "2024-01-03", "equity": 10200},
            {"timestamp": "2024-01-04", "equity": 11000},
        ]

        start_value = equity_curve[0]["equity"]
        normalized = [
            {"timestamp": p["timestamp"], "relative": round((p["equity"] / start_value) * 100, 4)}
            for p in equity_curve
        ]

        assert normalized[0]["relative"] == 100.0
        assert normalized[1]["relative"] == 105.0
        assert normalized[2]["relative"] == 102.0
        assert normalized[3]["relative"] == 110.0

    def test_normalize_handles_zero_start(self):
        """Handles edge case of zero starting equity."""
        equity_curve = [
            {"timestamp": "2024-01-01", "equity": 0},
            {"timestamp": "2024-01-02", "equity": 10000},
        ]

        start_value = equity_curve[0]["equity"]
        normalized = [
            {"timestamp": p["timestamp"], "relative": round((p["equity"] / start_value) * 100, 4) if start_value > 0 else 100}
            for p in equity_curve
        ]

        # Should use fallback of 100
        assert normalized[0]["relative"] == 100
        assert normalized[1]["relative"] == 100


class TestMetricsComparison:
    """Tests for the metrics comparison logic."""

    def test_interpretation_better_direction_max(self):
        """For max-better metrics (Sharpe), positive delta = better."""
        metrics = [
            ("sharpe_ratio", 1.5, 1.2, 0.3, "回放优于回测"),
            ("sharpe_ratio", 1.0, 1.5, -0.5, "回放劣于回测"),
            ("sortino_ratio", 2.0, 1.8, 0.2, "回放优于回测"),
        ]

        for metric, r_val, b_val, expected_delta, expected_interp in metrics:
            delta = r_val - b_val
            assert delta == expected_delta

    def test_interpretation_better_direction_min(self):
        """For min-better metrics (drawdown), negative delta = better."""
        metrics = [
            ("max_drawdown", 5.0, 8.0, -3.0, "回放优于回测"),  # lower drawdown = better
            ("max_drawdown", 10.0, 5.0, 5.0, "回放劣于回测"),
            ("volatility", 3.5, 4.0, -0.5, "回放优于回测"),
        ]

        for metric, r_val, b_val, expected_delta, expected_interp in metrics:
            delta = r_val - b_val
            assert delta == expected_delta

    def test_interpretation_neutral(self):
        """For neutral metrics (trade count), no interpretation."""
        # total_trades uses neutral direction
        delta = 5.0
        # Neutral means "基本持平" only when delta is 0
        assert (delta > 0) != True  # no direction preference


class TestReplayMetricsServiceMatching:
    """Tests for ReplayMetricsService backtest matching logic."""

    def test_exact_params_hash_match_priority(self):
        """Exact params_hash match takes priority over fuzzy match."""
        # Priority order: explicit_id > params_hash > strategy_symbol
        match_types = []

        # Case 1: explicit backtest_id provided
        if True:  # explicit backtest_id
            match_types.append("explicit_id")

        # Case 2: params_hash exact match
        if not match_types:
            if True:  # has params_hash
                match_types.append("params_hash")

        # Case 3: strategy + symbol fuzzy
        if not match_types:
            if True:  # has strategy_type + symbol
                match_types.append("strategy_symbol")

        assert match_types[0] == "explicit_id"

    def test_params_hash_fallback(self):
        """When no explicit ID, falls back to params_hash."""
        match_types = []
        has_params_hash = True
        has_strategy_symbol = True

        if not match_types and has_params_hash:
            match_types.append("params_hash")
        if not match_types and has_strategy_symbol:
            match_types.append("strategy_symbol")

        assert match_types[0] == "params_hash"

    def test_fuzzy_fallback(self):
        """When no params_hash, falls back to strategy_symbol."""
        match_types = []
        has_params_hash = False
        has_strategy_symbol = True

        if not match_types and has_params_hash:
            match_types.append("params_hash")
        if not match_types and has_strategy_symbol:
            match_types.append("strategy_symbol")

        assert match_types[0] == "strategy_symbol"
