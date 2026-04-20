from scripts.dynamic_selection_backtest import FormalJudgment, build_formal_judgment_text
from scripts.dynamic_selection_batch_validation import (
    BatchValidationCase,
    BatchValidationResult,
    BatchValidationSummary,
    build_mechanism_judgment,
    build_mechanism_judgment_text,
)


def test_single_sample_text_only_outputs_sample_level_judgment():
    judgment = FormalJudgment(
        conclusion="样本内有效",
        verdict="当前样本内动态选择相对固定等权更优。",
        reasons=["收益更高", "夏普更高"],
    )

    text = build_formal_judgment_text(judgment)

    assert "样本内判断" in text
    assert "机制级判断" not in text


def test_multi_sample_text_outputs_mechanism_level_judgment():
    case = BatchValidationCase("BTC/USDT", "4h", "2025-01-01", "2025-06-01")
    summary = BatchValidationSummary(
        dynamic_win_rate=0.75,
        median_return_diff=0.04,
        median_sharpe_diff=0.20,
        median_drawdown_diff=0.03,
        worst_case=BatchValidationResult(case, -0.02, -0.01, 0.4, 0.5, 0.18, 0.17),
    )

    judgment = build_mechanism_judgment(summary)
    text = build_mechanism_judgment_text(judgment)

    assert "机制级判断" in text
    assert "样本内判断" not in text


def test_stability_improvement_is_not_judged_as_simple_failure():
    case = BatchValidationCase("ETH/USDT", "4h", "2025-01-01", "2025-06-01")
    summary = BatchValidationSummary(
        dynamic_win_rate=0.45,
        median_return_diff=-0.01,
        median_sharpe_diff=0.08,
        median_drawdown_diff=0.05,
        worst_case=BatchValidationResult(case, -0.05, -0.01, 0.2, 0.3, 0.22, 0.18),
    )

    judgment = build_mechanism_judgment(summary)

    assert judgment.conclusion != "机制无效"
