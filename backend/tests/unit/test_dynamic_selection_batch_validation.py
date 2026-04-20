import pytest

from scripts.dynamic_selection_batch_validation import (
    BatchValidationCase,
    BatchValidationResult,
    summarize_batch_validation,
    validate_batch_cases,
)


def test_validate_batch_cases_runs_multiple_cases():
    cases = [
        BatchValidationCase("BTC/USDT", "4h", "2025-01-01", "2025-06-01"),
        BatchValidationCase("ETH/USDT", "1d", "2025-01-01", "2025-06-01"),
    ]

    def fake_runner(case: BatchValidationCase) -> BatchValidationResult:
        base_return = 0.10 if case.symbol == "BTC/USDT" else 0.02
        return BatchValidationResult(
            case=case,
            dynamic_total_return=base_return,
            fixed_total_return=base_return - 0.03,
            dynamic_sharpe=1.1,
            fixed_sharpe=0.8,
            dynamic_max_drawdown=0.12,
            fixed_max_drawdown=0.15,
        )

    results = validate_batch_cases(cases, fake_runner)
    assert len(results) == 2
    assert results[0].case.symbol == "BTC/USDT"
    assert results[1].case.interval == "1d"


def test_batch_summary_reports_win_rate_median_diffs_and_worst_case():
    cases = [
        BatchValidationCase("BTC/USDT", "4h", "2025-01-01", "2025-06-01"),
        BatchValidationCase("ETH/USDT", "4h", "2025-02-01", "2025-07-01"),
        BatchValidationCase("BTC/USDT", "1d", "2025-03-01", "2025-08-01"),
    ]
    results = [
        BatchValidationResult(cases[0], 0.12, 0.08, 1.2, 0.9, 0.10, 0.13),
        BatchValidationResult(cases[1], -0.03, -0.01, 0.5, 0.6, 0.18, 0.16),
        BatchValidationResult(cases[2], 0.06, 0.01, 0.9, 0.4, 0.11, 0.20),
    ]

    summary = summarize_batch_validation(results)

    assert summary.dynamic_win_rate == pytest.approx(2 / 3)
    assert summary.median_return_diff == pytest.approx(0.04)
    assert summary.median_sharpe_diff == pytest.approx(0.3)
    assert summary.median_drawdown_diff == pytest.approx(0.03)
    assert summary.worst_case.case.symbol == "ETH/USDT"
