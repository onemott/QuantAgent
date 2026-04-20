import argparse
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Callable, List

from scripts.dynamic_selection_backtest import (
    create_backtest,
    DEFAULT_COMMISSION_RATE,
    DEFAULT_EVALUATION_DAYS,
    DEFAULT_INITIAL_CAPITAL,
    fetch_klines,
    load_klines_csv,
    OUTPUT_DIR,
    resolve_evaluation_period_bars,
)


@dataclass
class BatchValidationCase:
    symbol: str
    interval: str
    start: str
    end: str


@dataclass
class BatchValidationResult:
    case: BatchValidationCase
    dynamic_total_return: float
    fixed_total_return: float
    dynamic_sharpe: float
    fixed_sharpe: float
    dynamic_max_drawdown: float
    fixed_max_drawdown: float

    @property
    def return_diff(self) -> float:
        return self.dynamic_total_return - self.fixed_total_return

    @property
    def sharpe_diff(self) -> float:
        return self.dynamic_sharpe - self.fixed_sharpe

    @property
    def drawdown_diff(self) -> float:
        return self.fixed_max_drawdown - self.dynamic_max_drawdown

    @property
    def is_dynamic_win(self) -> bool:
        return self.return_diff > 0


@dataclass
class BatchValidationSummary:
    dynamic_win_rate: float
    median_return_diff: float
    median_sharpe_diff: float
    median_drawdown_diff: float
    worst_case: BatchValidationResult


@dataclass
class MechanismJudgment:
    conclusion: str
    verdict: str
    reasons: List[str]


def validate_batch_cases(
    cases: List[BatchValidationCase],
    runner: Callable[[BatchValidationCase], BatchValidationResult],
) -> List[BatchValidationResult]:
    return [runner(case) for case in cases]


def summarize_batch_validation(results: List[BatchValidationResult]) -> BatchValidationSummary:
    if not results:
        raise ValueError("results must not be empty")

    dynamic_win_rate = sum(1 for result in results if result.is_dynamic_win) / len(results)
    median_return_diff = median(result.return_diff for result in results)
    median_sharpe_diff = median(result.sharpe_diff for result in results)
    median_drawdown_diff = median(result.drawdown_diff for result in results)
    worst_case = min(results, key=lambda result: result.return_diff)
    return BatchValidationSummary(
        dynamic_win_rate=dynamic_win_rate,
        median_return_diff=median_return_diff,
        median_sharpe_diff=median_sharpe_diff,
        median_drawdown_diff=median_drawdown_diff,
        worst_case=worst_case,
    )


def build_mechanism_judgment(summary: BatchValidationSummary) -> MechanismJudgment:
    reasons = [
        f"动态胜率为 {summary.dynamic_win_rate:.2%}",
        f"收益中位数差异为 {summary.median_return_diff:+.2%}",
        f"夏普中位数差异为 {summary.median_sharpe_diff:+.2f}",
        f"回撤中位数差异为 {summary.median_drawdown_diff:+.2%}",
    ]

    if (
        summary.dynamic_win_rate >= 0.6
        and summary.median_return_diff > 0
        and summary.median_sharpe_diff >= 0
        and summary.median_drawdown_diff >= 0
    ):
        return MechanismJudgment(
            conclusion="机制有效",
            verdict="多样本结果显示动态选择机制具备较稳定的整体优势。",
            reasons=reasons,
        )

    if (
        summary.median_return_diff <= 0
        and summary.median_sharpe_diff <= 0
        and summary.median_drawdown_diff <= 0
    ):
        return MechanismJudgment(
            conclusion="机制无效",
            verdict="多样本结果未显示动态选择机制相对固定等权有稳定优势。",
            reasons=reasons,
        )

    if summary.median_drawdown_diff > 0 and (summary.median_sharpe_diff > 0 or summary.dynamic_win_rate >= 0.5):
        return MechanismJudgment(
            conclusion="稳健性改善",
            verdict="收益结论仍混合，但多样本稳定性指标已有改善，不宜简单判负。",
            reasons=reasons,
        )

    return MechanismJudgment(
        conclusion="机制不确定",
        verdict="多样本结果仍然混合，需要继续扩大样本和观察稳定性。",
        reasons=reasons,
    )


def build_mechanism_judgment_text(judgment: MechanismJudgment) -> str:
    lines = [
        "机制级判断",
        "----------",
        f"结论: {judgment.conclusion}",
        f"说明: {judgment.verdict}",
        "依据:",
    ]
    for reason in judgment.reasons:
        lines.append(f"- {reason}")
    return "\n".join(lines)


def run_validation_case(case: BatchValidationCase) -> BatchValidationResult:
    evaluation_period_bars = resolve_evaluation_period_bars(
        case.interval,
        DEFAULT_EVALUATION_DAYS,
        None,
    )

    csv_path = Path(OUTPUT_DIR).parent / f"kline_cache_{case.symbol.replace('/', '')}_{case.interval}.csv"
    if csv_path.exists():
        df = load_klines_csv(str(csv_path))
    else:
        df = fetch_klines(case.symbol, case.interval, case.start, case.end)

    dynamic_report = create_backtest(
        df=df,
        enable_dynamic_selection=True,
        evaluation_period_bars=evaluation_period_bars,
        capital=DEFAULT_INITIAL_CAPITAL,
        commission=DEFAULT_COMMISSION_RATE,
        symbol=case.symbol,
        interval=case.interval,
    ).run()
    fixed_report = create_backtest(
        df=df,
        enable_dynamic_selection=False,
        evaluation_period_bars=evaluation_period_bars,
        capital=DEFAULT_INITIAL_CAPITAL,
        commission=DEFAULT_COMMISSION_RATE,
        symbol=case.symbol,
        interval=case.interval,
    ).run()

    return BatchValidationResult(
        case=case,
        dynamic_total_return=dynamic_report.metrics.total_return,
        fixed_total_return=fixed_report.metrics.total_return,
        dynamic_sharpe=dynamic_report.metrics.sharpe_ratio,
        fixed_sharpe=fixed_report.metrics.sharpe_ratio,
        dynamic_max_drawdown=dynamic_report.metrics.max_drawdown,
        fixed_max_drawdown=fixed_report.metrics.max_drawdown,
    )


def build_default_cases() -> List[BatchValidationCase]:
    return [
        BatchValidationCase("BTC/USDT", "4h", "2025-01-01", "2025-06-30"),
        BatchValidationCase("ETH/USDT", "4h", "2025-01-01", "2025-06-30"),
        BatchValidationCase("BTC/USDT", "1d", "2025-03-01", "2025-12-31"),
    ]


def format_batch_summary(summary: BatchValidationSummary) -> str:
    worst_case = summary.worst_case.case
    mechanism_judgment = build_mechanism_judgment(summary)
    return "\n".join(
        [
            "多样本验证汇总",
            "------------",
            f"动态胜率: {summary.dynamic_win_rate:.2%}",
            f"收益中位数差异: {summary.median_return_diff:+.2%}",
            f"夏普中位数差异: {summary.median_sharpe_diff:+.2f}",
            f"回撤中位数差异: {summary.median_drawdown_diff:+.2%}",
            f"最差样本: {worst_case.symbol} {worst_case.interval} {worst_case.start} -> {worst_case.end}",
            "",
            build_mechanism_judgment_text(mechanism_judgment),
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="动态选择多样本批量验证")
    parser.add_argument("--symbols", type=str, default="BTC/USDT,ETH/USDT")
    parser.add_argument("--intervals", type=str, default="4h,1d")
    parser.add_argument("--ranges", type=str, default="2025-01-01:2025-06-30,2025-03-01:2025-12-31")
    return parser.parse_args()


def parse_cases_from_args(args: argparse.Namespace) -> List[BatchValidationCase]:
    symbols = [item.strip() for item in args.symbols.split(",") if item.strip()]
    intervals = [item.strip() for item in args.intervals.split(",") if item.strip()]
    ranges = [item.strip() for item in args.ranges.split(",") if item.strip()]
    cases: List[BatchValidationCase] = []
    for symbol in symbols:
        for interval in intervals:
            for date_range in ranges:
                start, end = [item.strip() for item in date_range.split(":", 1)]
                cases.append(BatchValidationCase(symbol, interval, start, end))
    return cases


def main() -> None:
    args = parse_args()
    cases = parse_cases_from_args(args)
    results = validate_batch_cases(cases, run_validation_case)
    summary = summarize_batch_validation(results)
    print(format_batch_summary(summary))


if __name__ == "__main__":
    main()
