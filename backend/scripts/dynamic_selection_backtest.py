"""
动态策略选择对比回测脚本

用途：
1. 复用 `BinanceService` 获取同一份历史 K 线数据
2. 复用项目现有回测引擎与动态选择组件
3. 对比“开启动态策略选择”与“关闭动态策略选择（固定等权）”两种场景
4. 输出统一、可读的绩效对比表格

用法示例：
    cd d:\\Desktop\\QuantAgent\\backend
    python -m scripts.dynamic_selection_backtest
    python -m scripts.dynamic_selection_backtest --enable-dynamic-selection
    python -m scripts.dynamic_selection_backtest --disable-dynamic-selection
    python -m scripts.dynamic_selection_backtest --symbol ETH/USDT --interval 1h --evaluation-days 60
    python -m scripts.dynamic_selection_backtest --csv scripts/kline_cache_BTCUSDT_4h.csv
"""

import argparse
import asyncio
import logging
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pandas as pd
from dotenv import load_dotenv

# 确保能导入 app 模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
load_dotenv(env_path)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def configure_script_logging() -> None:
    # 正式结论脚本默认压低子策略逐笔日志，避免掩盖最终对比结果。
    logging.getLogger("app.core.strategy").setLevel(logging.WARNING)
    logging.getLogger("app.strategies.signal_based_strategy").setLevel(logging.WARNING)


DEFAULT_SYMBOL = "BTC/USDT"
DEFAULT_INTERVAL = "4h"
DEFAULT_LOOKBACK_DAYS = 365
DEFAULT_INITIAL_CAPITAL = 10000.0
DEFAULT_COMMISSION_RATE = 0.001
DEFAULT_EVALUATION_DAYS = 90
WEIGHT_METHOD = "score_based"
MIN_WEIGHT_FLOOR = 0.05
MAX_WEIGHT_STEP_CHANGE = 0.10
MAX_SINGLE_STRATEGY_WEIGHT = 0.25

TREND_STRATEGIES = ["ma", "ema_triple", "turtle", "atr_trend", "macd", "ichimoku"]
OSCILLATOR_STRATEGIES = ["rsi", "boll"]
MAX_WEIGHT_PER_STRATEGY = 0.40

STRATEGY_TYPES = [
    "ma",
    "rsi",
    "boll",
    "macd",
    "ema_triple",
    "atr_trend",
    "turtle",
    "ichimoku",
]

ELIMINATION_RULE = {
    "min_score_threshold": 25.0,
    "elimination_ratio": 0.2,
    "min_consecutive_low": 3,
    "low_score_threshold": 45.0,
    "min_strategies": 4,
}

REVIVAL_RULE = {
    "revival_score_threshold": 40.0,
    "min_consecutive_high": 1,
    "max_revival_per_round": 3,
}

SCENARIO_DYNAMIC = "开启动态选择"
SCENARIO_FIXED = "关闭动态选择"


def get_default_date_range() -> tuple[str, str]:
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=DEFAULT_LOOKBACK_DAYS)
    return start_dt.date().isoformat(), end_dt.date().isoformat()


DEFAULT_START_DATE, DEFAULT_END_DATE = get_default_date_range()


@dataclass
class PerformanceSnapshot:
    total_return: float = 0.0
    annualized_return: float = 0.0
    max_drawdown_pct: float = 0.0
    volatility: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    final_capital: float = 0.0
    equity_curve: List[float] = field(default_factory=list)


@dataclass
class StrategyScore:
    strategy_id: str
    score: float
    return_score: float
    risk_score: float
    risk_adjusted_score: float
    stability_score: float
    efficiency_score: float
    rank: int = 0


@dataclass
class RankedStrategyLite:
    strategy_id: str
    score: float
    rank: int
    evaluation: Any


@dataclass
class CycleResult:
    cycle_index: int
    window_start: datetime
    window_end: datetime
    applied_weights: Dict[str, float]
    next_weights: Dict[str, float]
    strategy_scores: Dict[str, StrategyScore]
    surviving_strategies: List[str]
    eliminated_strategies: List[str]
    revived_strategies: List[str]
    elimination_reasons: Dict[str, str]
    revival_reasons: Dict[str, str]
    strategy_states: Dict[str, str] = field(default_factory=dict)
    market_state: str = ""
    adx_value: float = 0.0
    portfolio_return: float = 0.0
    group_target_weights: Dict[str, float] = field(default_factory=dict)
    primary_downweight_reasons: List[str] = field(default_factory=list)
    primary_upweight_reasons: List[str] = field(default_factory=list)


@dataclass
class ScenarioMetrics:
    initial_capital: float
    final_capital: float
    total_return: float
    annualized_return: float
    max_drawdown: float
    sharpe_ratio: float
    win_rate: float
    total_trades: int
    winning_trades: int


@dataclass
class ScenarioReport:
    scenario_name: str
    enable_dynamic_selection: bool
    evaluation_period_bars: int
    metrics: ScenarioMetrics
    cycle_results: List[CycleResult]


@dataclass
class FormalJudgment:
    conclusion: str
    verdict: str
    reasons: List[str]


CACHE_DIR = Path(__file__).parent
OUTPUT_DIR = CACHE_DIR / "output"
INTERVAL_RE = re.compile(r"^(?P<count>\d+)(?P<unit>[mhdwM])$")


def parse_date(date_text: str) -> datetime:
    return datetime.strptime(date_text, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def interval_to_timedelta(interval: str) -> timedelta:
    match = INTERVAL_RE.match(interval)
    if not match:
        raise ValueError(f"不支持解析的 K 线周期: {interval}")
    count = int(match.group("count"))
    unit = match.group("unit")
    if unit == "m":
        return timedelta(minutes=count)
    if unit == "h":
        return timedelta(hours=count)
    if unit == "d":
        return timedelta(days=count)
    if unit == "w":
        return timedelta(weeks=count)
    if unit == "M":
        return timedelta(days=30 * count)
    raise ValueError(f"不支持解析的 K 线周期: {interval}")


def resolve_evaluation_period_bars(interval: str, evaluation_days: int, evaluation_bars: Optional[int]) -> int:
    if evaluation_bars is not None and evaluation_bars > 0:
        return evaluation_bars
    bar_delta = interval_to_timedelta(interval)
    return max(1, int(round(timedelta(days=evaluation_days) / bar_delta)))


def resolve_window_bounds_from_index(
    index: pd.DatetimeIndex,
    current_bar_count: int,
    evaluation_period_bars: int,
) -> tuple[datetime, datetime]:
    if len(index) == 0:
        raise ValueError("无法从空的 K 线索引解析评估窗口。")
    if current_bar_count <= 0:
        raise ValueError("current_bar_count 必须大于 0。")

    end_idx = min(current_bar_count - 1, len(index) - 1)
    start_idx = max(0, end_idx - evaluation_period_bars + 1)
    window_start = index[start_idx].to_pydatetime()
    window_end = index[end_idx].to_pydatetime()
    if window_start.tzinfo is None:
        window_start = window_start.replace(tzinfo=timezone.utc)
    if window_end.tzinfo is None:
        window_end = window_end.replace(tzinfo=timezone.utc)
    return window_start, window_end


def ensure_dataframe_columns(df: pd.DataFrame) -> pd.DataFrame:
    col_mapping = {
        "o": "open",
        "h": "high",
        "l": "low",
        "c": "close",
        "v": "volume",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
    }
    normalized = df.rename(columns=col_mapping).copy()
    required_cols = ["open", "high", "low", "close", "volume"]
    missing = [column for column in required_cols if column not in normalized.columns]
    if missing:
        raise ValueError(f"K 线数据缺少必要列: {missing}")
    if not isinstance(normalized.index, pd.DatetimeIndex):
        raise ValueError("K 线数据索引必须为 DatetimeIndex。")
    normalized = normalized.sort_index()
    normalized.index = pd.to_datetime(normalized.index, utc=True)
    return normalized[required_cols]


def get_cache_path(symbol: str, interval: str) -> Path:
    symbol_clean = symbol.replace("/", "")
    return CACHE_DIR / f"kline_cache_{symbol_clean}_{interval}.csv"


def save_klines_cache(df: pd.DataFrame, symbol: str, interval: str) -> None:
    cache_path = get_cache_path(symbol, interval)
    data = df.copy()
    data.index.name = "timestamp"
    data.to_csv(cache_path, index=True)
    logger.info("K 线缓存已保存: %s", cache_path)


def load_klines_cache(symbol: str, interval: str) -> Optional[pd.DataFrame]:
    cache_path = get_cache_path(symbol, interval)
    if not cache_path.exists():
        return None

    df = pd.read_csv(cache_path)
    time_col = next((col for col in ["timestamp", "time", "datetime", "date", "open_time"] if col in df.columns), df.columns[0])
    df[time_col] = pd.to_datetime(df[time_col], utc=True)
    df = df.set_index(time_col)
    df = ensure_dataframe_columns(df)
    logger.info("已从本地缓存加载 K 线: %s", cache_path)
    return df


async def fetch_klines_from_binance_with_retry(
    symbol: str,
    interval: str,
    start_date: str,
    end_date: str,
    max_retries: int = 3,
    retry_delay: int = 10,
) -> pd.DataFrame:
    from app.services.binance_service import binance_service

    start_dt = parse_date(start_date)
    end_dt = parse_date(end_date)
    step = interval_to_timedelta(interval)

    for attempt in range(1, max_retries + 1):
        try:
            logger.info("从 Binance 拉取历史 K 线: %s %s, 第 %s/%s 次尝试", symbol, interval, attempt, max_retries)
            current_start = start_dt
            batches: List[pd.DataFrame] = []

            while current_start < end_dt:
                batch_df = await binance_service.get_klines_dataframe(
                    symbol=symbol,
                    timeframe=interval,
                    limit=1000,
                    start=current_start,
                    end=end_dt,
                )
                if batch_df is None or batch_df.empty:
                    break

                batch_df = ensure_dataframe_columns(batch_df)
                batches.append(batch_df)

                last_timestamp = batch_df.index[-1].to_pydatetime()
                if last_timestamp.tzinfo is None:
                    last_timestamp = last_timestamp.replace(tzinfo=timezone.utc)
                next_start = last_timestamp + step
                if next_start <= current_start:
                    break
                current_start = next_start
                await asyncio.sleep(0.2)

            if not batches:
                raise ValueError(f"未获取到 {symbol} {interval} 的 K 线数据")

            df = pd.concat(batches)
            df = df[~df.index.duplicated(keep="last")]
            df = ensure_dataframe_columns(df)
            df = df[(df.index >= start_dt) & (df.index <= end_dt)]
            save_klines_cache(df, symbol, interval)
            logger.info("K 线获取成功，共 %s 根，范围 %s ~ %s", len(df), df.index[0], df.index[-1])
            return df
        except Exception as exc:
            logger.warning("拉取 K 线失败（第 %s/%s 次）: %s", attempt, max_retries, exc)
            if attempt == max_retries:
                raise
            await asyncio.sleep(retry_delay)


def fetch_klines(symbol: str, interval: str, start_date: str, end_date: str) -> pd.DataFrame:
    try:
        return asyncio.run(fetch_klines_from_binance_with_retry(symbol, interval, start_date, end_date))
    except Exception as exc:
        logger.error("实时拉取 K 线失败，尝试回退本地缓存: %s", exc)
        cached = load_klines_cache(symbol, interval)
        if cached is not None:
            start_dt = parse_date(start_date)
            end_dt = parse_date(end_date)
            filtered = cached[(cached.index >= start_dt) & (cached.index <= end_dt)]
            if not filtered.empty:
                return filtered
        raise ValueError("无法获取 K 线数据，请检查网络或使用 --csv 指定数据文件。") from exc


def load_klines_csv(csv_path: str) -> pd.DataFrame:
    logger.info("从 CSV 加载 K 线数据: %s", csv_path)
    df = pd.read_csv(csv_path)
    time_col = next((col for col in ["timestamp", "time", "datetime", "date", "open_time"] if col in df.columns), df.columns[0])
    df[time_col] = pd.to_datetime(df[time_col], utc=True)
    df = df.set_index(time_col)
    df = ensure_dataframe_columns(df)
    logger.info("CSV 数据加载成功，共 %s 根，范围 %s ~ %s", len(df), df.index[0], df.index[-1])
    return df


def calculate_adx(df: pd.DataFrame, period: int = 14) -> float:
    if len(df) < period + 1:
        return 25.0

    high = df["high"].copy()
    low = df["low"].copy()
    close = df["close"].copy()

    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0
    plus_dm[plus_dm <= minus_dm] = 0
    minus_dm[minus_dm <= plus_dm] = 0

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.ewm(alpha=1 / period, min_periods=period).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1 / period, min_periods=period).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(alpha=1 / period, min_periods=period).mean() / atr)
    dx = ((plus_di - minus_di).abs() / (plus_di + minus_di)) * 100
    adx = dx.ewm(alpha=1 / period, min_periods=period).mean()

    value = adx.iloc[-1]
    return float(value) if pd.notna(value) else 25.0


def detect_market_regime(df: pd.DataFrame) -> tuple[str, float]:
    from app.services.dynamic_selection.regime_detector import RegimeDetector

    result = RegimeDetector().detect(df)
    return result.regime, result.adx_value


def apply_market_regime_bonus(scores: Dict[str, StrategyScore], market_state: str) -> Dict[str, StrategyScore]:
    adjusted: Dict[str, StrategyScore] = {}
    for strategy_id, score in scores.items():
        multiplier = 1.0
        if market_state == "trend" and strategy_id in TREND_STRATEGIES:
            multiplier = 1.1
        elif market_state == "oscillating" and strategy_id in OSCILLATOR_STRATEGIES:
            multiplier = 1.1

        adjusted[strategy_id] = StrategyScore(
            strategy_id=score.strategy_id,
            score=round(min(score.score * multiplier, 100.0), 2),
            return_score=score.return_score,
            risk_score=score.risk_score,
            risk_adjusted_score=score.risk_adjusted_score,
            stability_score=score.stability_score,
            efficiency_score=score.efficiency_score,
            rank=score.rank,
        )
    return adjusted


def build_signal_functions(strategy_types: List[str]) -> Dict[str, Callable]:
    from app.services.strategy_templates import build_signal_func, get_template_default_params

    signal_funcs: Dict[str, Callable] = {}
    logger.info("初始化原子策略信号函数...")
    for strategy_type in strategy_types:
        params = get_template_default_params(strategy_type)
        signal_funcs[strategy_type] = build_signal_func(strategy_type, params)
        logger.info("  - %s: %s", strategy_type, params)
    return signal_funcs


def generate_atomic_signals(
    df: pd.DataFrame,
    signal_funcs: Dict[str, Callable],
    strategy_types: List[str],
) -> Dict[str, pd.Series]:
    from app.services.backtester.signal_resolution import resolve_signal_output

    atomic_signals: Dict[str, pd.Series] = {}
    for strategy_id in strategy_types:
        signal = resolve_signal_output(signal_funcs[strategy_id](df))
        series = pd.Series(signal, index=df.index).fillna(0).astype(int)
        atomic_signals[strategy_id] = series
    return atomic_signals


def run_backtest_for_strategy(
    df: pd.DataFrame,
    signal_func: Callable,
    initial_capital: float,
    commission: float,
) -> PerformanceSnapshot:
    from app.services.backtester.event_driven import EventDrivenBacktester
    from app.services.metrics_calculator import MetricsCalculator

    engine = EventDrivenBacktester(
        df=df,
        signal_func=signal_func,
        initial_capital=initial_capital,
        commission=commission,
    )
    result = engine.run()
    trades = result.get("trades", [])
    winning_trades = sum(1 for trade in trades if float(trade.get("pnl", 0.0)) > 0)

    equity_points = [
        {"timestamp": timestamp, "equity": equity}
        for timestamp, equity in zip(df.index, result.get("equity_curve", []))
    ]
    standardized = MetricsCalculator.calculate_from_equity_points(
        equity_points=equity_points,
        initial_capital=initial_capital,
        total_trades=int(result.get("total_trades", 0)),
        winning_trades=winning_trades,
    )

    return PerformanceSnapshot(
        total_return=standardized.total_return,
        annualized_return=standardized.annualized_return,
        max_drawdown_pct=standardized.max_drawdown_pct,
        volatility=standardized.volatility,
        sharpe_ratio=standardized.sharpe_ratio,
        sortino_ratio=standardized.sortino_ratio,
        calmar_ratio=standardized.calmar_ratio,
        win_rate=standardized.win_rate,
        total_trades=standardized.total_trades,
        winning_trades=winning_trades,
        final_capital=standardized.final_capital,
        equity_curve=[float(value) for value in result.get("equity_curve", [])],
    )


def calculate_strategy_scores(performance: PerformanceSnapshot) -> Dict[str, float]:
    from app.services.dynamic_selection.evaluator import StrategyEvaluator

    return StrategyEvaluator.calculate_scores(asdict(performance))


def apply_elimination(
    ranked_strategies: List[RankedStrategyLite],
    elimination_rule: Dict[str, Any],
    consecutive_low_counts: Dict[str, int],
) -> tuple[List[Any], List[Any], Dict[str, str]]:
    from app.services.dynamic_selection.eliminator import EliminationRule, StrategyEliminator

    rule = EliminationRule(
        min_score_threshold=elimination_rule["min_score_threshold"],
        elimination_ratio=elimination_rule["elimination_ratio"],
        min_consecutive_low=elimination_rule["min_consecutive_low"],
        low_score_threshold=elimination_rule["low_score_threshold"],
        min_strategies=elimination_rule["min_strategies"],
    )
    eliminator = StrategyEliminator()
    return eliminator.apply_elimination(ranked_strategies, rule, consecutive_low_counts)


def check_revival(
    hibernating_scores: Dict[str, float],
    consecutive_high_counts: Dict[str, int],
    revival_rule: Dict[str, Any],
) -> tuple[List[str], Dict[str, int], Dict[str, str]]:
    from app.services.dynamic_selection.eliminator import RevivalRule, StrategyEliminator

    rule = RevivalRule(
        revival_score_threshold=revival_rule["revival_score_threshold"],
        min_consecutive_high=revival_rule["min_consecutive_high"],
        max_revival_per_round=revival_rule["max_revival_per_round"],
    )
    return StrategyEliminator.check_revival(hibernating_scores, consecutive_high_counts, rule)


def allocate_weights(strategies: List[RankedStrategyLite], method: str) -> Dict[str, float]:
    from app.services.dynamic_selection.weight_allocator import WeightAllocator

    allocator = WeightAllocator()
    return allocator.allocate_weights(
        strategies,
        method=method,
        min_weight_floor=MIN_WEIGHT_FLOOR,
        max_single_strategy_weight=MAX_SINGLE_STRATEGY_WEIGHT,
    )


def allocate_equal_weights(strategy_ids: List[str]) -> Dict[str, float]:
    ranked = [RankedStrategyLite(strategy_id=sid, score=0.0, rank=idx + 1, evaluation=None) for idx, sid in enumerate(strategy_ids)]
    return allocate_weights(ranked, method="equal")


def evaluate_strategy_bus_in_window(
    strategy_id: str,
    bus: Any,
    evaluator: Any,
    window_start: datetime,
    window_end: datetime,
    evaluation_date: datetime,
):
    performance = bus.get_performance_metric_in_window(window_start, window_end)
    return evaluator.evaluate(
        strategy_id=strategy_id,
        performance=performance,
        window_start=window_start,
        window_end=window_end,
        evaluation_date=evaluation_date,
    )


def constrain_weight_step_change(
    previous_weights: Dict[str, float],
    target_weights: Dict[str, float],
    max_step_change: float,
) -> Dict[str, float]:
    strategy_ids = unique_preserve_order(list(previous_weights.keys()) + list(target_weights.keys()))
    constrained: Dict[str, float] = {}
    for strategy_id in strategy_ids:
        previous = previous_weights.get(strategy_id, 0.0)
        target = target_weights.get(strategy_id, 0.0)
        delta = target - previous
        if delta > max_step_change:
            constrained[strategy_id] = previous + max_step_change
        elif delta < -max_step_change:
            constrained[strategy_id] = previous - max_step_change
        else:
            constrained[strategy_id] = target
    return constrained


def smooth_weight_transition(
    previous_weights: Dict[str, float],
    target_weights: Dict[str, float],
    blend_old: float,
    blend_new: float,
    min_weight_floor: float,
    max_single_strategy_weight: float,
) -> Dict[str, float]:
    if blend_old < 0 or blend_new < 0:
        raise ValueError("blend weights must be non-negative")

    strategy_ids = unique_preserve_order(list(previous_weights.keys()) + list(target_weights.keys()))
    blended = {
        strategy_id: previous_weights.get(strategy_id, 0.0) * blend_old
        + target_weights.get(strategy_id, 0.0) * blend_new
        for strategy_id in strategy_ids
    }

    total_blended = sum(blended.values())
    if total_blended <= 0:
        equal_weight = 1.0 / len(strategy_ids) if strategy_ids else 0.0
        blended = {strategy_id: equal_weight for strategy_id in strategy_ids}
    else:
        blended = {
            strategy_id: weight / total_blended
            for strategy_id, weight in blended.items()
        }

    from app.services.dynamic_selection.weight_allocator import WeightAllocator

    return WeightAllocator._apply_weight_constraints(
        blended,
        min_weight_floor=min_weight_floor,
        max_single_strategy_weight=max_single_strategy_weight,
    )


def build_weight_reason_summary(
    market_state: str,
    group_target_weights: Dict[str, float],
    eliminated_ids: List[str],
) -> tuple[List[str], List[str]]:
    upweight_reasons: List[str] = []
    downweight_reasons: List[str] = []

    trend_weight = group_target_weights.get("trend", 0.0)
    oscillator_weight = group_target_weights.get("oscillator", 0.0)

    if market_state in {"trend_up", "trend_down"}:
        upweight_reasons.append(f"趋势族在 {market_state} 市场获配 {format_percent(trend_weight)}")
        downweight_reasons.append(f"震荡族在 {market_state} 市场降至 {format_percent(oscillator_weight)}")
    elif market_state == "range":
        upweight_reasons.append(f"震荡族在震荡市获配 {format_percent(oscillator_weight)}")
        downweight_reasons.append(f"趋势族在震荡市降至 {format_percent(trend_weight)}")
    elif market_state == "high_vol":
        upweight_reasons.append("高波动阶段优先分散配置，避免单一策略过度集中")
        downweight_reasons.append("高波动阶段压低单策略权重上限")

    if eliminated_ids:
        downweight_reasons.append(f"以下策略触发极端条件休眠: {', '.join(eliminated_ids)}")

    return downweight_reasons, upweight_reasons


def unique_preserve_order(items: List[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def build_effective_weights(
    strategy_ids: List[str],
    weights: Dict[str, float],
    states: Dict[str, str],
) -> Dict[str, float]:
    effective_weights: Dict[str, float] = {}
    for strategy_id in strategy_ids:
        state = states.get(strategy_id, "alive")
        if state == "hibernating":
            continue
        weight = weights.get(strategy_id, 0.0)
        if state == "cooldown":
            weight *= 0.5
        if weight > 0:
            effective_weights[strategy_id] = weight
    return effective_weights


def combine_weighted_signals(
    df: pd.DataFrame,
    atomic_signals: Dict[str, pd.Series],
    weights: Dict[str, float],
    threshold: float = 0.5,
) -> pd.Series:
    from app.strategies.composition.weighted import WeightedComposer

    composer = WeightedComposer(
        composition_id="dynamic_selection_backtest",
        weights=weights,
        threshold=threshold,
    )
    return asyncio.run(composer.combine_signals(df, atomic_signals))


def run_combined_backtest(
    df: pd.DataFrame,
    combined_signal: pd.Series,
    initial_capital: float,
    commission: float,
) -> Dict[str, Any]:
    from app.services.backtester.event_driven import EventDrivenBacktester

    backtester = EventDrivenBacktester(
        df=df,
        signal_func=lambda _: combined_signal,
        initial_capital=initial_capital,
        commission=commission,
    )
    return backtester.run()


class DynamicSelectionBacktest:
    """
    用“生产语义”做回测：
    1. 每根 K 线逐步驱动每个子策略的虚拟账户
    2. 动态场景按真实动态选择逻辑评估、淘汰、复活、调权
    3. 固定场景使用同一套子策略虚拟持仓，但始终保持全量等权

    这样得到的对比才是公平对标，可用于输出正式判断。
    """

    def __init__(
        self,
        df: pd.DataFrame,
        strategy_types: List[str],
        evaluation_period_bars: int,
        initial_capital: float,
        commission: float,
        enable_dynamic_selection: bool,
        scenario_name: str,
        symbol: str,
        interval: str,
        weight_method: str = WEIGHT_METHOD,
    ):
        from app.services.dynamic_selection.eliminator import EliminationRule, RevivalRule, StrategyEliminator
        from app.services.dynamic_selection.evaluator import StrategyEvaluator
        from app.services.dynamic_selection.ranker import StrategyRanker
        from app.services.dynamic_selection.strategy_grouping import StrategyGrouping
        from app.services.dynamic_selection.weight_allocator import WeightAllocator

        self.df = ensure_dataframe_columns(df)
        self.strategy_types = strategy_types
        self.evaluation_period_bars = evaluation_period_bars
        self.initial_capital = initial_capital
        self.commission = commission
        self.enable_dynamic_selection = enable_dynamic_selection
        self.scenario_name = scenario_name
        self.symbol = symbol
        self.interval = interval
        self.weight_method = weight_method

        self.evaluator = StrategyEvaluator()
        self.ranker = StrategyRanker()
        self.eliminator = StrategyEliminator()
        self.strategy_grouping = StrategyGrouping()
        self.weight_allocator = WeightAllocator()
        self.elimination_rule = EliminationRule(**ELIMINATION_RULE)
        self.revival_rule = RevivalRule(**REVIVAL_RULE)

        self.main_bus = self._create_virtual_bus(initial_capital)
        self.alive_strategies: Dict[str, Any] = {}
        self.virtual_buses: Dict[str, Any] = {}
        self.hibernating_strategies: Dict[str, Any] = {}
        self.hibernating_buses: Dict[str, Any] = {}
        self.consecutive_low_counts: Dict[str, int] = {}
        self.consecutive_high_counts: Dict[str, int] = {}
        self.current_weights: Dict[str, float] = allocate_equal_weights(strategy_types)
        self.strategy_states: Dict[str, str] = {strategy_id: "alive" for strategy_id in strategy_types}
        self.cycle_results: List[CycleResult] = []
        self.portfolio_equity_points: List[Dict[str, Any]] = []
        self.current_position = 0.0
        self.bar_count = 0
        self.last_evaluation_bar_index = 0
        self._last_evaluation_datetime: Optional[datetime] = None
        self._initial_evaluation_done = False

        self._initialize_atomic_strategies()

    def _create_virtual_bus(self, initial_capital: float):
        from app.core.virtual_bus import VirtualTradingBus

        return VirtualTradingBus(initial_capital=initial_capital)

    def _initialize_atomic_strategies(self) -> None:
        from app.strategies.signal_based_strategy import SignalBasedStrategy

        if not self.strategy_types:
            raise ValueError("未配置原子策略，无法执行正式回测。")

        per_strategy_capital = self.initial_capital / len(self.strategy_types)
        for strategy_id in self.strategy_types:
            vbus = self._create_virtual_bus(per_strategy_capital)
            strategy = SignalBasedStrategy(
                strategy_id=strategy_id,
                bus=vbus,
                strategy_type=strategy_id,
            )
            # 这里显式使用本地默认参数，避免触发 strategy_templates 中的数据库默认参数加载，
            # 从而保证脚本作为独立正式回测工具时不会引入额外的异步数据库资源。
            strategy.set_parameters(strategy._get_default_params())
            self.alive_strategies[strategy_id] = strategy
            self.virtual_buses[strategy_id] = vbus
            self.consecutive_low_counts[strategy_id] = 0

    def _build_regime_alignment(self, strategy_ids: List[str], market_state: str) -> Dict[str, bool]:
        if market_state in {"trend_up", "trend_down"}:
            preferred_group = "trend"
        elif market_state == "range":
            preferred_group = "oscillator"
        else:
            preferred_group = None

        alignment: Dict[str, bool] = {}
        for strategy_id in strategy_ids:
            group = self.strategy_grouping.get_strategy_group(strategy_id)
            alignment[strategy_id] = preferred_group is None or group == preferred_group
        return alignment

    def run(self) -> ScenarioReport:
        return asyncio.run(self._run_async())

    async def _run_async(self) -> ScenarioReport:
        total_bars = len(self.df)
        if total_bars < 2:
            raise ValueError("K 线数量不足，至少需要 2 根 K 线才能回测。")

        logger.info("")
        logger.info("%s", "=" * 72)
        logger.info("开始回测场景: %s", self.scenario_name)
        logger.info("组合语义: 逐 bar 虚拟持仓聚合（与生产动态策略一致）")
        logger.info("动态选择: %s", "开启" if self.enable_dynamic_selection else "关闭")
        logger.info("数据总量: %s 根 K 线", total_bars)
        logger.info("评估周期: %s 根 K 线", self.evaluation_period_bars)

        for timestamp, row in self.df.iterrows():
            bar = self._build_bar(timestamp, row)
            await self.main_bus.publish_bar(bar)
            await self._dispatch_atomic_bar(bar)

            self.bar_count += 1
            if self.enable_dynamic_selection:
                await self._maybe_run_evaluation(bar)

            signal = self._compose_signal()
            await self._execute_signal(signal, bar)

        self._finalize_equity_points()
        return self._build_report()

    def _build_bar(self, timestamp: pd.Timestamp, row: pd.Series):
        from app.models.trading import BarData

        bar_time = timestamp.to_pydatetime()
        if bar_time.tzinfo is None:
            bar_time = bar_time.replace(tzinfo=timezone.utc)
        return BarData(
            symbol=self.symbol.replace("/", ""),
            interval=self.interval,
            datetime=bar_time,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
        )

    async def _dispatch_atomic_bar(self, bar) -> None:
        for strategy_id, strategy in list(self.alive_strategies.items()):
            await self.virtual_buses[strategy_id].publish_bar(bar)
            await strategy.on_bar(bar)

        for strategy_id, strategy in list(self.hibernating_strategies.items()):
            await self.hibernating_buses[strategy_id].publish_bar(bar)
            await strategy.on_bar(bar)

    async def _maybe_run_evaluation(self, bar) -> None:
        if not self._initial_evaluation_done:
            initial_trigger = max(10, int(self.evaluation_period_bars * 0.1))
            if self.bar_count >= initial_trigger:
                await self._run_evaluation(bar, is_initial=True)
                self._initial_evaluation_done = True

        if self.bar_count - self.last_evaluation_bar_index >= self.evaluation_period_bars:
            await self._run_evaluation(bar, is_initial=False)

    async def _run_evaluation(self, bar, is_initial: bool) -> None:
        if not self.alive_strategies:
            return

        applied_weights = self.current_weights.copy()
        window_start, window_end = resolve_window_bounds_from_index(
            self.df.index,
            current_bar_count=self.bar_count,
            evaluation_period_bars=self.evaluation_period_bars,
        )
        window_df = self.df.loc[window_start:window_end]
        market_state, adx_value = detect_market_regime(window_df)
        evaluations = []
        score_book: Dict[str, StrategyScore] = {}

        for strategy_id in self.alive_strategies:
            evaluation = evaluate_strategy_bus_in_window(
                strategy_id=strategy_id,
                bus=self.virtual_buses[strategy_id],
                evaluator=self.evaluator,
                window_start=window_start,
                window_end=window_end,
                evaluation_date=bar.datetime,
            )
            evaluations.append(evaluation)
            score_book[strategy_id] = StrategyScore(
                strategy_id=strategy_id,
                score=evaluation.total_score,
                return_score=evaluation.return_score,
                risk_score=evaluation.risk_score,
                risk_adjusted_score=evaluation.risk_adjusted_score,
                stability_score=evaluation.stability_score,
                efficiency_score=evaluation.efficiency_score,
                rank=evaluation.rank or 0,
            )

        ranked = self.ranker.rank_evaluations(evaluations)
        for ranked_strategy in ranked:
            if ranked_strategy.strategy_id in score_book:
                score_book[ranked_strategy.strategy_id].rank = ranked_strategy.rank

        regime_alignment = self._build_regime_alignment(
            [ranked_strategy.strategy_id for ranked_strategy in ranked],
            market_state,
        )
        surviving, eliminated, elimination_reasons = self.eliminator.apply_soft_elimination(
            ranked,
            rule=self.elimination_rule,
            consecutive_low_counts=self.consecutive_low_counts,
            regime_alignment=regime_alignment,
        )

        for ranked_strategy in surviving:
            if ranked_strategy.score < self.elimination_rule.low_score_threshold:
                self.consecutive_low_counts[ranked_strategy.strategy_id] = (
                    self.consecutive_low_counts.get(ranked_strategy.strategy_id, 0) + 1
                )
            else:
                self.consecutive_low_counts[ranked_strategy.strategy_id] = 0

        eliminated_ids: List[str] = []
        for ranked_strategy in eliminated:
            strategy_id = ranked_strategy.strategy_id
            eliminated_ids.append(strategy_id)
            self.strategy_states[strategy_id] = "hibernating"
            self.hibernating_strategies[strategy_id] = self.alive_strategies.pop(strategy_id)
            self.hibernating_buses[strategy_id] = self.virtual_buses.pop(strategy_id)
            self.consecutive_high_counts[strategy_id] = 0

        hibernating_scores: Dict[str, float] = {}
        for strategy_id in self.hibernating_strategies:
            evaluation = evaluate_strategy_bus_in_window(
                strategy_id=strategy_id,
                bus=self.hibernating_buses[strategy_id],
                evaluator=self.evaluator,
                window_start=window_start,
                window_end=window_end,
                evaluation_date=bar.datetime,
            )
            hibernating_scores[strategy_id] = evaluation.total_score

        revived_ids, self.consecutive_high_counts, revival_reasons = self.eliminator.check_revival(
            hibernating_scores,
            self.consecutive_high_counts,
            self.revival_rule,
        )

        for strategy_id in revived_ids:
            self.alive_strategies[strategy_id] = self.hibernating_strategies.pop(strategy_id)
            self.virtual_buses[strategy_id] = self.hibernating_buses.pop(strategy_id)
            self.strategy_states[strategy_id] = "alive"
            self.consecutive_low_counts[strategy_id] = 0
            self.consecutive_high_counts.pop(strategy_id, None)

        surviving_ids = [ranked_strategy.strategy_id for ranked_strategy in surviving]
        target_weights, group_target_weights = self.strategy_grouping.allocate_grouped_weights(
            surviving,
            market_state=market_state,
            allocator=self.weight_allocator,
            method=self.weight_method,
        )
        bounded_weights = constrain_weight_step_change(
            applied_weights,
            target_weights,
            max_step_change=MAX_WEIGHT_STEP_CHANGE,
        )
        next_weights = smooth_weight_transition(
            applied_weights,
            bounded_weights,
            blend_old=0.7,
            blend_new=0.3,
            min_weight_floor=MIN_WEIGHT_FLOOR,
            max_single_strategy_weight=MAX_SINGLE_STRATEGY_WEIGHT,
        )
        self.current_weights = next_weights.copy()
        primary_downweight_reasons, primary_upweight_reasons = build_weight_reason_summary(
            market_state,
            group_target_weights,
            eliminated_ids,
        )

        for strategy_id in self.strategy_types:
            if strategy_id in self.hibernating_strategies:
                self.strategy_states[strategy_id] = "hibernating"
            elif strategy_id in self.alive_strategies:
                self.strategy_states[strategy_id] = "alive"
            else:
                self.strategy_states[strategy_id] = "inactive"

        cycle_result = CycleResult(
            cycle_index=len(self.cycle_results) + 1,
            window_start=window_start,
            window_end=window_end,
            applied_weights=applied_weights,
            next_weights=next_weights.copy(),
            strategy_scores=score_book,
            surviving_strategies=surviving_ids,
            eliminated_strategies=eliminated_ids,
            revived_strategies=revived_ids,
            elimination_reasons=elimination_reasons,
            revival_reasons=revival_reasons,
            strategy_states=self.strategy_states.copy(),
            market_state=market_state,
            adx_value=adx_value,
            portfolio_return=0.0,
            group_target_weights=group_target_weights,
            primary_downweight_reasons=primary_downweight_reasons,
            primary_upweight_reasons=primary_upweight_reasons,
        )
        self.cycle_results.append(cycle_result)
        self._print_cycle_summary(cycle_result, is_initial=is_initial)

        self._last_evaluation_datetime = bar.datetime
        self.last_evaluation_bar_index = self.bar_count

    def _compose_signal(self) -> int:
        strategy_ids = list(self.alive_strategies.keys()) if self.enable_dynamic_selection else list(self.virtual_buses.keys())
        if not strategy_ids:
            return 0

        if self.enable_dynamic_selection:
            weights = self.current_weights
        else:
            weights = allocate_equal_weights(strategy_ids)

        weighted_sum = 0.0
        total_weight = 0.0
        for strategy_id in strategy_ids:
            position = self.virtual_buses[strategy_id].router.position
            signal = 1 if position > 0 else (-1 if position < 0 else 0)
            weight = weights.get(strategy_id, 0.0)
            weighted_sum += signal * weight
            total_weight += abs(weight)

        if total_weight <= 0:
            return 0

        weighted_sum /= total_weight
        if weighted_sum >= 0.5:
            return 1
        if weighted_sum <= -0.5:
            return -1
        return 0

    async def _execute_signal(self, signal: int, bar) -> None:
        from app.models.trading import OrderRequest, OrderType, TradeSide

        if self.current_position == 0 and signal == 1:
            balance_info = await self.main_bus.get_balance()
            available_capital = balance_info.get("available_balance", 0.0)
            if available_capital <= 0 or bar.close <= 0:
                return

            slippage_pct = 0.0005
            effective_price = bar.close * (1 + slippage_pct)
            use_capital = min(self.initial_capital, available_capital)
            quantity = use_capital / (effective_price * (1 + self.commission))
            if quantity <= 0:
                return

            order_req = OrderRequest(
                symbol=bar.symbol,
                side=TradeSide.BUY,
                quantity=quantity,
                price=bar.close,
                order_type=OrderType.MARKET,
                strategy_id=self.scenario_name,
            )
            result = await self.main_bus.execute_order(order_req)
            if result.status == "FILLED":
                self.current_position = result.filled_quantity

        elif self.current_position > 0 and signal <= 0:
            order_req = OrderRequest(
                symbol=bar.symbol,
                side=TradeSide.SELL,
                quantity=self.current_position,
                price=bar.close,
                order_type=OrderType.MARKET,
                strategy_id=self.scenario_name,
            )
            result = await self.main_bus.execute_order(order_req)
            if result.status == "FILLED":
                self.current_position = 0.0

    def _finalize_equity_points(self) -> None:
        self.portfolio_equity_points = [
            {"timestamp": timestamp, "equity": float(equity)}
            for timestamp, equity in self.main_bus.router.equity_curve
        ]

    def _build_report(self) -> ScenarioReport:
        from app.services.metrics_calculator import MetricsCalculator

        metrics_snapshot = MetricsCalculator.calculate_from_equity_points(
            equity_points=self.portfolio_equity_points,
            initial_capital=self.initial_capital,
            total_trades=self.main_bus.router.trade_count,
            winning_trades=self.main_bus.router.winning_trades,
        )

        metrics = ScenarioMetrics(
            initial_capital=self.initial_capital,
            final_capital=metrics_snapshot.final_capital,
            total_return=metrics_snapshot.total_return,
            annualized_return=metrics_snapshot.annualized_return,
            max_drawdown=metrics_snapshot.max_drawdown_pct,
            sharpe_ratio=metrics_snapshot.sharpe_ratio,
            win_rate=metrics_snapshot.win_rate,
            total_trades=metrics_snapshot.total_trades,
            winning_trades=self.main_bus.router.winning_trades,
        )
        return ScenarioReport(
            scenario_name=self.scenario_name,
            enable_dynamic_selection=self.enable_dynamic_selection,
            evaluation_period_bars=self.evaluation_period_bars,
            metrics=metrics,
            cycle_results=self.cycle_results,
        )

    def _print_cycle_summary(self, cycle_result: CycleResult, is_initial: bool) -> None:
        stage = "初始评估" if is_initial else "周期评估"
        logger.info("")
        logger.info("[%s] %s #%s @ %s", self.scenario_name, stage, cycle_result.cycle_index, cycle_result.window_end)
        logger.info(
            "  市场状态 %-10s | ADX %6.2f | 窗口 %s -> %s",
            cycle_result.market_state,
            cycle_result.adx_value,
            cycle_result.window_start,
            cycle_result.window_end,
        )
        ranked_scores = sorted(
            cycle_result.strategy_scores.items(),
            key=lambda item: item[1].score,
            reverse=True,
        )
        for strategy_id, score in ranked_scores:
            next_weight = cycle_result.next_weights.get(strategy_id, 0.0)
            logger.info(
                "  %-12s | 分数 %6.2f | 下轮权重 %7s | 状态 %s",
                strategy_id,
                score.score,
                format_percent(next_weight),
                cycle_result.strategy_states.get(strategy_id, "alive"),
            )

        if cycle_result.eliminated_strategies:
            logger.info("[%s] 本轮休眠: %s", self.scenario_name, ", ".join(cycle_result.eliminated_strategies))
        if cycle_result.revived_strategies:
            logger.info("[%s] 本轮复活: %s", self.scenario_name, ", ".join(cycle_result.revived_strategies))


def format_percent(value: float, signed: bool = False) -> str:
    fmt = "{:+.2%}" if signed else "{:.2%}"
    return fmt.format(value)


def format_drawdown(value: float) -> str:
    return f"-{value * 100:.2f}%"


def format_ratio(value: float, signed: bool = False) -> str:
    return f"{value:+.2f}" if signed else f"{value:.2f}"


def format_int(value: int, signed: bool = False) -> str:
    return f"{value:+d}" if signed else f"{value:d}"


def build_single_scenario_table(report: ScenarioReport) -> str:
    metrics = report.metrics
    rows = [
        ("总收益率", format_percent(metrics.total_return), ""),
        ("年化收益率", format_percent(metrics.annualized_return), ""),
        ("最大回撤", format_drawdown(metrics.max_drawdown), ""),
        ("夏普比率", format_ratio(metrics.sharpe_ratio), ""),
        ("胜率", format_percent(metrics.win_rate), ""),
        ("交易次数", format_int(metrics.total_trades), ""),
        ("最终资金", f"{metrics.final_capital:,.2f} USDT", ""),
    ]

    metric_width = max(len(row[0]) for row in rows)
    value_width = max(len(row[1]) for row in rows)
    lines = [
        f"场景: {report.scenario_name}",
        "-" * (metric_width + value_width + 7),
        f"{'指标'.ljust(metric_width)} | {'数值'.ljust(value_width)}",
        "-" * (metric_width + value_width + 7),
    ]
    for metric, value, _ in rows:
        lines.append(f"{metric.ljust(metric_width)} | {value.rjust(value_width)}")
    return "\n".join(lines)


def build_comparison_table(dynamic_report: ScenarioReport, fixed_report: ScenarioReport) -> str:
    dynamic_metrics = dynamic_report.metrics
    fixed_metrics = fixed_report.metrics
    rows = [
        (
            "总收益率",
            format_percent(dynamic_metrics.total_return),
            format_percent(fixed_metrics.total_return),
            format_percent(dynamic_metrics.total_return - fixed_metrics.total_return, signed=True),
        ),
        (
            "年化收益率",
            format_percent(dynamic_metrics.annualized_return),
            format_percent(fixed_metrics.annualized_return),
            format_percent(dynamic_metrics.annualized_return - fixed_metrics.annualized_return, signed=True),
        ),
        (
            "最大回撤",
            format_drawdown(dynamic_metrics.max_drawdown),
            format_drawdown(fixed_metrics.max_drawdown),
            format_percent(fixed_metrics.max_drawdown - dynamic_metrics.max_drawdown, signed=True),
        ),
        (
            "夏普比率",
            format_ratio(dynamic_metrics.sharpe_ratio),
            format_ratio(fixed_metrics.sharpe_ratio),
            format_ratio(dynamic_metrics.sharpe_ratio - fixed_metrics.sharpe_ratio, signed=True),
        ),
        (
            "胜率",
            format_percent(dynamic_metrics.win_rate),
            format_percent(fixed_metrics.win_rate),
            format_percent(dynamic_metrics.win_rate - fixed_metrics.win_rate, signed=True),
        ),
        (
            "交易次数",
            format_int(dynamic_metrics.total_trades),
            format_int(fixed_metrics.total_trades),
            format_int(dynamic_metrics.total_trades - fixed_metrics.total_trades, signed=True),
        ),
        (
            "最终资金",
            f"{dynamic_metrics.final_capital:,.2f}",
            f"{fixed_metrics.final_capital:,.2f}",
            f"{dynamic_metrics.final_capital - fixed_metrics.final_capital:+,.2f}",
        ),
    ]

    metric_width = max(len(row[0]) for row in rows)
    dynamic_width = max(len(row[1]) for row in rows + [("场景", dynamic_report.scenario_name, "", "")])
    fixed_width = max(len(row[2]) for row in rows + [("场景", fixed_report.scenario_name, "", "")])
    diff_width = max(len(row[3]) for row in rows + [("场景", "差异", "", "")])

    total_width = metric_width + dynamic_width + fixed_width + diff_width + 13
    lines = [
        "动态策略选择对比结果",
        "-" * total_width,
        f"{'指标'.ljust(metric_width)} | "
        f"{dynamic_report.scenario_name.ljust(dynamic_width)} | "
        f"{fixed_report.scenario_name.ljust(fixed_width)} | "
        f"{'差异'.rjust(diff_width)}",
        "-" * total_width,
    ]
    for metric, dynamic_value, fixed_value, diff_value in rows:
        lines.append(
            f"{metric.ljust(metric_width)} | "
            f"{dynamic_value.rjust(dynamic_width)} | "
            f"{fixed_value.rjust(fixed_width)} | "
            f"{diff_value.rjust(diff_width)}"
        )
    return "\n".join(lines)


def build_formal_judgment(dynamic_report: ScenarioReport, fixed_report: ScenarioReport) -> FormalJudgment:
    dynamic_metrics = dynamic_report.metrics
    fixed_metrics = fixed_report.metrics
    reasons: List[str] = []

    if dynamic_metrics.total_trades == 0 or fixed_metrics.total_trades == 0:
        if dynamic_metrics.total_trades == 0:
            reasons.append("动态场景未形成有效交易，样本不足以支持正式优劣判断")
        if fixed_metrics.total_trades == 0:
            reasons.append("固定等权基线未形成有效交易，比较基准不足以支持正式优劣判断")
        return FormalJudgment(
            conclusion="样本不足",
            verdict="当前公平对标样本未形成足够成交，不能据此输出正式优劣结论。",
            reasons=reasons,
        )

    if dynamic_metrics.total_return > fixed_metrics.total_return:
        reasons.append("动态选择的总收益率更高")
    else:
        reasons.append("动态选择的总收益率更低")

    if dynamic_metrics.sharpe_ratio > fixed_metrics.sharpe_ratio:
        reasons.append("动态选择的夏普比率更高")
    else:
        reasons.append("动态选择的夏普比率更低")

    if dynamic_metrics.max_drawdown < fixed_metrics.max_drawdown:
        reasons.append("动态选择的最大回撤更小")
    else:
        reasons.append("动态选择的最大回撤更大")

    if dynamic_metrics.win_rate > fixed_metrics.win_rate:
        reasons.append("动态选择的胜率更高")
    else:
        reasons.append("动态选择的胜率不占优")

    if (
        dynamic_metrics.total_return > fixed_metrics.total_return
        and dynamic_metrics.sharpe_ratio > fixed_metrics.sharpe_ratio
        and dynamic_metrics.max_drawdown < fixed_metrics.max_drawdown
    ):
        return FormalJudgment(
            conclusion="有效",
            verdict="在当前公平对标样本内，动态选择机制相对固定等权表现出明确优势。",
            reasons=reasons,
        )

    if (
        dynamic_metrics.total_return < fixed_metrics.total_return
        and dynamic_metrics.sharpe_ratio < fixed_metrics.sharpe_ratio
        and dynamic_metrics.max_drawdown > fixed_metrics.max_drawdown
    ):
        return FormalJudgment(
            conclusion="无效",
            verdict="在当前公平对标样本内，动态选择机制未提升表现，且风险收益特征劣于固定等权。",
            reasons=reasons,
        )

    return FormalJudgment(
        conclusion="不确定",
        verdict="在当前公平对标样本内，动态选择机制结果混合，尚不能认定其明确优于固定等权。",
        reasons=reasons,
    )


def build_formal_judgment_text(judgment: FormalJudgment) -> str:
    lines = [
        "样本内判断",
        "----------",
        f"结论: {judgment.conclusion}",
        f"说明: {judgment.verdict}",
        "依据:",
    ]
    for reason in judgment.reasons:
        lines.append(f"- {reason}")
    lines.append("注: 该判断仅针对当前单一样本区间，不代表机制级长期稳定性结论。")
    return "\n".join(lines)


def sanitize_filename_component(value: str) -> str:
    sanitized = value.strip()
    sanitized = re.sub(r'[<>:"/\\|?*]+', "_", sanitized)
    sanitized = re.sub(r"\s+", "_", sanitized)
    sanitized = re.sub(r"_+", "_", sanitized)
    sanitized = sanitized.strip(" ._")
    return sanitized or "report"


def build_report_stem(
    symbol: str,
    interval: str,
    start: str,
    end: str,
    mode_label: str,
) -> str:
    symbol_part = sanitize_filename_component(symbol.replace("/", ""))
    interval_part = sanitize_filename_component(interval)
    start_part = sanitize_filename_component(start)
    end_part = sanitize_filename_component(end)
    if mode_label == "compare":
        prefix = "动态选择对比报告"
    elif mode_label == "dynamic_only":
        prefix = "动态场景汇总"
    elif mode_label == "fixed_only":
        prefix = "固定等权场景汇总"
    else:
        prefix = "动态选择报告"
    prefix_part = sanitize_filename_component(prefix)
    return f"{prefix_part}_{symbol_part}_{interval_part}_{start_part}到{end_part}"


def build_single_scenario_dataframe(report: ScenarioReport) -> pd.DataFrame:
    metrics = report.metrics
    return pd.DataFrame(
        [
            {
                "场景": report.scenario_name,
                "总收益率": format_percent(metrics.total_return),
                "年化收益率": format_percent(metrics.annualized_return),
                "最大回撤": format_drawdown(metrics.max_drawdown),
                "夏普比率": format_ratio(metrics.sharpe_ratio),
                "胜率": format_percent(metrics.win_rate),
                "交易次数": format_int(metrics.total_trades),
                "盈利交易数": format_int(metrics.winning_trades),
                "最终资金(USDT)": f"{metrics.final_capital:,.2f}",
                "评估周期(K线)": format_int(report.evaluation_period_bars),
                "动态选择": "是" if report.enable_dynamic_selection else "否",
            }
        ]
    )


def build_cycle_details_text(report: ScenarioReport) -> str:
    if not report.cycle_results:
        return "周期详情\n--------\n无周期评估结果。"

    lines = ["周期详情", "--------"]
    for cycle in report.cycle_results:
        trend_weight = cycle.group_target_weights.get("trend", 0.0)
        oscillator_weight = cycle.group_target_weights.get("oscillator", 0.0)
        lines.extend(
            [
                f"周期 #{cycle.cycle_index}",
                f"窗口: {cycle.window_start} -> {cycle.window_end}",
                f"当前市场状态: {cycle.market_state}",
                f"趋势族目标权重: {format_percent(trend_weight)}",
                f"震荡族目标权重: {format_percent(oscillator_weight)}",
                f"本轮主要降权原因: {'; '.join(cycle.primary_downweight_reasons) if cycle.primary_downweight_reasons else '无'}",
                f"本轮主要加权原因: {'; '.join(cycle.primary_upweight_reasons) if cycle.primary_upweight_reasons else '无'}",
                "",
            ]
        )
    return "\n".join(lines).rstrip()


def build_cycle_details_dataframe(report: ScenarioReport) -> pd.DataFrame:
    rows = []
    for cycle in report.cycle_results:
        rows.append(
            {
                "场景": report.scenario_name,
                "周期序号": cycle.cycle_index,
                "窗口开始": cycle.window_start.isoformat(),
                "窗口结束": cycle.window_end.isoformat(),
                "当前市场状态": cycle.market_state,
                "ADX": f"{cycle.adx_value:.2f}",
                "趋势族目标权重": format_percent(cycle.group_target_weights.get("trend", 0.0)),
                "震荡族目标权重": format_percent(cycle.group_target_weights.get("oscillator", 0.0)),
                "本轮主要降权原因": "; ".join(cycle.primary_downweight_reasons),
                "本轮主要加权原因": "; ".join(cycle.primary_upweight_reasons),
            }
        )
    return pd.DataFrame(rows)


def build_comparison_dataframe(dynamic_report: ScenarioReport, fixed_report: ScenarioReport) -> pd.DataFrame:
    dynamic_metrics = dynamic_report.metrics
    fixed_metrics = fixed_report.metrics
    return pd.DataFrame(
        [
            {
                "指标": "总收益率",
                dynamic_report.scenario_name: format_percent(dynamic_metrics.total_return),
                fixed_report.scenario_name: format_percent(fixed_metrics.total_return),
                "差异": format_percent(dynamic_metrics.total_return - fixed_metrics.total_return, signed=True),
            },
            {
                "指标": "年化收益率",
                dynamic_report.scenario_name: format_percent(dynamic_metrics.annualized_return),
                fixed_report.scenario_name: format_percent(fixed_metrics.annualized_return),
                "差异": format_percent(dynamic_metrics.annualized_return - fixed_metrics.annualized_return, signed=True),
            },
            {
                "指标": "最大回撤",
                dynamic_report.scenario_name: format_drawdown(dynamic_metrics.max_drawdown),
                fixed_report.scenario_name: format_drawdown(fixed_metrics.max_drawdown),
                "差异": format_percent(fixed_metrics.max_drawdown - dynamic_metrics.max_drawdown, signed=True),
            },
            {
                "指标": "夏普比率",
                dynamic_report.scenario_name: format_ratio(dynamic_metrics.sharpe_ratio),
                fixed_report.scenario_name: format_ratio(fixed_metrics.sharpe_ratio),
                "差异": format_ratio(dynamic_metrics.sharpe_ratio - fixed_metrics.sharpe_ratio, signed=True),
            },
            {
                "指标": "胜率",
                dynamic_report.scenario_name: format_percent(dynamic_metrics.win_rate),
                fixed_report.scenario_name: format_percent(fixed_metrics.win_rate),
                "差异": format_percent(dynamic_metrics.win_rate - fixed_metrics.win_rate, signed=True),
            },
            {
                "指标": "交易次数",
                dynamic_report.scenario_name: format_int(dynamic_metrics.total_trades),
                fixed_report.scenario_name: format_int(fixed_metrics.total_trades),
                "差异": format_int(dynamic_metrics.total_trades - fixed_metrics.total_trades, signed=True),
            },
            {
                "指标": "最终资金(USDT)",
                dynamic_report.scenario_name: f"{dynamic_metrics.final_capital:,.2f}",
                fixed_report.scenario_name: f"{fixed_metrics.final_capital:,.2f}",
                "差异": f"{dynamic_metrics.final_capital - fixed_metrics.final_capital:+,.2f}",
            },
        ]
    )


def save_text_report(output_dir: Path, stem: str, content: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    txt_path = output_dir / f"{stem}.txt"
    txt_path.write_text(content, encoding="utf-8")
    return txt_path


def save_csv_report(output_dir: Path, stem: str, dataframe: pd.DataFrame) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"{stem}.csv"
    dataframe.to_csv(csv_path, index=False, encoding="utf-8-sig")
    return csv_path


def save_dual_scenario_reports(
    dynamic_report: ScenarioReport,
    fixed_report: ScenarioReport,
    judgment: FormalJudgment,
    args: argparse.Namespace,
) -> tuple[Path, Path]:
    stem = build_report_stem(
        symbol=args.symbol,
        interval=args.interval,
        start=args.start,
        end=args.end,
        mode_label="compare",
    )
    text_content = "\n\n".join(
        [
            build_comparison_table(dynamic_report, fixed_report),
            build_cycle_details_text(dynamic_report),
            build_formal_judgment_text(judgment),
        ]
    )
    csv_df = pd.concat(
        [
            build_comparison_dataframe(dynamic_report, fixed_report),
            pd.DataFrame([{}]),
            build_cycle_details_dataframe(dynamic_report),
        ],
        ignore_index=True,
    )
    txt_path = save_text_report(Path(args.output_dir), stem, text_content)
    csv_path = save_csv_report(Path(args.output_dir), stem, csv_df)
    return txt_path, csv_path


def save_single_scenario_reports(
    report: ScenarioReport,
    args: argparse.Namespace,
) -> tuple[Path, Path]:
    mode_label = "dynamic_only" if report.enable_dynamic_selection else "fixed_only"
    stem = build_report_stem(
        symbol=args.symbol,
        interval=args.interval,
        start=args.start,
        end=args.end,
        mode_label=mode_label,
    )
    text_content = build_single_scenario_table(report)
    if report.enable_dynamic_selection:
        text_content = "\n\n".join([text_content, build_cycle_details_text(report)])
        csv_df = pd.concat(
            [
                build_single_scenario_dataframe(report),
                pd.DataFrame([{}]),
                build_cycle_details_dataframe(report),
            ],
            ignore_index=True,
        )
    else:
        csv_df = build_single_scenario_dataframe(report)
    txt_path = save_text_report(Path(args.output_dir), stem, text_content)
    csv_path = save_csv_report(Path(args.output_dir), stem, csv_df)
    return txt_path, csv_path


def print_run_configuration(args: argparse.Namespace, evaluation_period_bars: int) -> None:
    logger.info("")
    logger.info("%s", "=" * 72)
    logger.info("回测配置")
    logger.info("交易对: %s", args.symbol)
    logger.info("时间范围: %s ~ %s", args.start, args.end)
    logger.info("K 线周期: %s", args.interval)
    logger.info("初始资金: %.2f USDT", args.capital)
    logger.info("评估周期: %s 根 K 线", evaluation_period_bars)
    logger.info("原子策略: %s", ", ".join(STRATEGY_TYPES))
    logger.info("比较口径: 生产语义公平对标（子策略虚拟持仓聚合）")
    if args.enable_dynamic_selection is None:
        logger.info("运行模式: 双场景对比")
    else:
        logger.info("运行模式: %s", "仅动态场景" if args.enable_dynamic_selection else "仅固定等权场景")


def create_backtest(
    df: pd.DataFrame,
    enable_dynamic_selection: bool,
    evaluation_period_bars: int,
    capital: float,
    commission: float,
    symbol: str,
    interval: str,
) -> DynamicSelectionBacktest:
    return DynamicSelectionBacktest(
        df=df,
        strategy_types=STRATEGY_TYPES,
        evaluation_period_bars=evaluation_period_bars,
        initial_capital=capital,
        commission=commission,
        enable_dynamic_selection=enable_dynamic_selection,
        scenario_name=SCENARIO_DYNAMIC if enable_dynamic_selection else SCENARIO_FIXED,
        symbol=symbol,
        interval=interval,
    )


async def close_binance_service_safely() -> None:
    try:
        from app.services.binance_service import binance_service

        await binance_service.close()
    except Exception as exc:
        logger.warning("关闭 BinanceService 资源时出现异常: %s", exc)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="动态策略选择对比回测脚本")
    parser.add_argument("--csv", type=str, default=None, help="可选，直接从 CSV 加载 K 线数据")
    parser.add_argument("--symbol", type=str, default=DEFAULT_SYMBOL, help=f"交易对，默认 {DEFAULT_SYMBOL}")
    parser.add_argument("--interval", type=str, default=DEFAULT_INTERVAL, help=f"K 线周期，默认 {DEFAULT_INTERVAL}")
    parser.add_argument("--start", type=str, default=DEFAULT_START_DATE, help=f"开始日期，默认 {DEFAULT_START_DATE}")
    parser.add_argument("--end", type=str, default=DEFAULT_END_DATE, help=f"结束日期，默认 {DEFAULT_END_DATE}")
    parser.add_argument("--capital", type=float, default=DEFAULT_INITIAL_CAPITAL, help=f"初始资金，默认 {DEFAULT_INITIAL_CAPITAL}")
    parser.add_argument("--commission", type=float, default=DEFAULT_COMMISSION_RATE, help=f"手续费率，默认 {DEFAULT_COMMISSION_RATE}")
    parser.add_argument("--evaluation-days", type=int, default=DEFAULT_EVALUATION_DAYS, help=f"评估窗口天数，默认 {DEFAULT_EVALUATION_DAYS}")
    parser.add_argument("--evaluation-bars", type=int, default=None, help="直接指定评估窗口 K 线根数，优先级高于 --evaluation-days")
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(OUTPUT_DIR),
        help=f"结果输出目录，默认 {OUTPUT_DIR}",
    )

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--enable-dynamic-selection", dest="enable_dynamic_selection", action="store_true", help="仅运行开启动态策略选择场景")
    mode_group.add_argument("--disable-dynamic-selection", dest="enable_dynamic_selection", action="store_false", help="仅运行关闭动态策略选择场景")
    parser.set_defaults(enable_dynamic_selection=None)
    return parser.parse_args()


def main() -> None:
    configure_script_logging()
    args = parse_args()
    evaluation_period_bars = resolve_evaluation_period_bars(args.interval, args.evaluation_days, args.evaluation_bars)
    print_run_configuration(args, evaluation_period_bars)
    try:
        if args.csv:
            df = load_klines_csv(args.csv)
        else:
            df = fetch_klines(args.symbol, args.interval, args.start, args.end)

        if args.enable_dynamic_selection is None:
            dynamic_report = create_backtest(
                df=df,
                enable_dynamic_selection=True,
                evaluation_period_bars=evaluation_period_bars,
                capital=args.capital,
                commission=args.commission,
                symbol=args.symbol,
                interval=args.interval,
            ).run()
            fixed_report = create_backtest(
                df=df,
                enable_dynamic_selection=False,
                evaluation_period_bars=evaluation_period_bars,
                capital=args.capital,
                commission=args.commission,
                symbol=args.symbol,
                interval=args.interval,
            ).run()
            judgment = build_formal_judgment(dynamic_report, fixed_report)
            txt_path, csv_path = save_dual_scenario_reports(dynamic_report, fixed_report, judgment, args)

            print("")
            print(build_comparison_table(dynamic_report, fixed_report))
            print("")
            print(build_formal_judgment_text(judgment))
            print("")
            print(f"TXT 已保存: {txt_path}")
            print(f"CSV 已保存: {csv_path}")
        else:
            report = create_backtest(
                df=df,
                enable_dynamic_selection=args.enable_dynamic_selection,
                evaluation_period_bars=evaluation_period_bars,
                capital=args.capital,
                commission=args.commission,
                symbol=args.symbol,
                interval=args.interval,
            ).run()
            txt_path, csv_path = save_single_scenario_reports(report, args)
            print("")
            print(build_single_scenario_table(report))
            print("")
            print(f"TXT 已保存: {txt_path}")
            print(f"CSV 已保存: {csv_path}")
    finally:
        asyncio.run(close_binance_service_safely())


if __name__ == "__main__":
    main()
