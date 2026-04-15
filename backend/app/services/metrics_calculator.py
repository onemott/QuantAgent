import logging
import math
from enum import Enum
from typing import Any, Dict, Mapping, Sequence

import pandas as pd
from pydantic import BaseModel, Field

from app.services.backtester.annualization import (
    DEFAULT_ANNUALIZATION_FACTOR,
    DEFAULT_RISK_FREE_RATE,
    annualize_sharpe,
    infer_annualization_factor,
)


logger = logging.getLogger(__name__)


class MetricValueType(str, Enum):
    DECIMAL = "decimal"
    PERCENTAGE = "percentage"
    ABSOLUTE_VALUE = "absolute_value"


class StandardizedMetricsSnapshot(BaseModel):
    """
    Canonical cross-module metrics snapshot.

    All ratio-style metrics use decimal format in this model:
    - `0.12` means 12%
    - `0.25` drawdown means 25%
    """

    initial_capital: float = 0.0
    final_capital: float = 0.0
    total_return: float = 0.0
    annualized_return: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    volatility: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    annualization_factor: int = DEFAULT_ANNUALIZATION_FACTOR
    metric_types: Dict[str, MetricValueType] = Field(
        default_factory=lambda: {
            "initial_capital": MetricValueType.ABSOLUTE_VALUE,
            "final_capital": MetricValueType.ABSOLUTE_VALUE,
            "total_return": MetricValueType.DECIMAL,
            "annualized_return": MetricValueType.DECIMAL,
            "max_drawdown": MetricValueType.ABSOLUTE_VALUE,
            "max_drawdown_pct": MetricValueType.DECIMAL,
            "volatility": MetricValueType.DECIMAL,
            "sharpe_ratio": MetricValueType.DECIMAL,
            "sortino_ratio": MetricValueType.DECIMAL,
            "calmar_ratio": MetricValueType.DECIMAL,
            "win_rate": MetricValueType.DECIMAL,
            "total_trades": MetricValueType.ABSOLUTE_VALUE,
            "winning_trades": MetricValueType.ABSOLUTE_VALUE,
            "losing_trades": MetricValueType.ABSOLUTE_VALUE,
            "annualization_factor": MetricValueType.ABSOLUTE_VALUE,
        }
    )

    class Config:
        use_enum_values = True

    @classmethod
    def from_source(cls, source: Any) -> "StandardizedMetricsSnapshot":
        """
        Normalize metrics from mixed legacy sources.

        Preferred path:
        - consume explicit `metric_types` when present
        Fallback path:
        - infer legacy percentage payloads using conservative heuristics
        - otherwise assume canonical decimal ratios
        """
        raw_metric_types = cls._read_value(source, "metric_types", None)
        if isinstance(raw_metric_types, Mapping):
            return cls.from_typed_source(source, raw_metric_types)

        if cls._looks_like_percentage_source(source):
            logger.warning(
                "Metrics source has no metric_types metadata; falling back to percentage heuristic normalization."
            )
            return cls.from_percentage_mapping(cls._extract_mapping(source))

        return cls.from_decimal_source(source)

    @classmethod
    def from_decimal_source(cls, source: Any) -> "StandardizedMetricsSnapshot":
        """Build a canonical snapshot from ORM or VirtualBus objects that already use decimal ratios."""
        return cls(
            initial_capital=float(
                cls._read_value(source, "initial_capital", cls._read_value(source, "initial_equity", 0.0)) or 0.0
            ),
            final_capital=float(
                cls._read_value(source, "final_capital", cls._read_value(source, "final_equity", 0.0)) or 0.0
            ),
            total_return=float(cls._read_value(source, "total_return", 0.0) or 0.0),
            annualized_return=float(
                cls._read_value(source, "annualized_return", cls._read_value(source, "annual_return", 0.0)) or 0.0
            ),
            max_drawdown=float(
                cls._read_value(source, "max_drawdown", 0.0) or 0.0
            ),
            max_drawdown_pct=float(
                cls._read_value(source, "max_drawdown_pct", cls._read_value(source, "max_drawdown", 0.0)) or 0.0
            ),
            volatility=float(cls._read_value(source, "volatility", 0.0) or 0.0),
            sharpe_ratio=float(cls._read_value(source, "sharpe_ratio", 0.0) or 0.0),
            sortino_ratio=float(cls._read_value(source, "sortino_ratio", 0.0) or 0.0),
            calmar_ratio=float(cls._read_value(source, "calmar_ratio", 0.0) or 0.0),
            win_rate=float(cls._read_value(source, "win_rate", 0.0) or 0.0),
            total_trades=int(cls._read_value(source, "total_trades", 0) or 0),
            winning_trades=int(cls._read_value(source, "winning_trades", 0) or 0),
            losing_trades=int(cls._read_value(source, "losing_trades", 0) or 0),
            annualization_factor=int(cls._read_value(source, "annualization_factor", DEFAULT_ANNUALIZATION_FACTOR) or DEFAULT_ANNUALIZATION_FACTOR),
        )

    @classmethod
    def from_typed_source(
        cls,
        source: Any,
        metric_types: Mapping[str, Any],
    ) -> "StandardizedMetricsSnapshot":
        """Build a canonical snapshot using explicit unit metadata from the source payload."""
        typed_metric_types = {key: str(value) for key, value in metric_types.items()}
        return cls(
            initial_capital=cls._normalize_absolute_value(
                cls._read_value(source, "initial_capital", cls._read_value(source, "initial_equity", 0.0))
            ),
            final_capital=cls._normalize_absolute_value(
                cls._read_value(source, "final_capital", cls._read_value(source, "final_equity", 0.0))
            ),
            total_return=cls._normalize_ratio_value(
                cls._read_value(source, "total_return", 0.0),
                typed_metric_types.get("total_return", MetricValueType.DECIMAL.value),
            ),
            annualized_return=cls._normalize_ratio_value(
                cls._read_value(source, "annualized_return", cls._read_value(source, "annual_return", 0.0)),
                typed_metric_types.get(
                    "annualized_return",
                    typed_metric_types.get("annual_return", MetricValueType.DECIMAL.value),
                ),
            ),
            max_drawdown=cls._normalize_absolute_value(
                cls._read_value(
                    source,
                    "max_drawdown_amount",
                    cls._read_value(source, "max_drawdown", 0.0)
                    if typed_metric_types.get("max_drawdown", MetricValueType.ABSOLUTE_VALUE.value)
                    == MetricValueType.ABSOLUTE_VALUE.value
                    else 0.0,
                )
            ),
            max_drawdown_pct=cls._normalize_ratio_value(
                cls._read_value(
                    source,
                    "max_drawdown_pct",
                    cls._read_value(source, "max_drawdown", 0.0),
                ),
                typed_metric_types.get(
                    "max_drawdown_pct",
                    typed_metric_types.get("max_drawdown", MetricValueType.DECIMAL.value),
                ),
            ),
            volatility=cls._normalize_ratio_value(
                cls._read_value(source, "volatility", 0.0),
                typed_metric_types.get("volatility", MetricValueType.DECIMAL.value),
            ),
            sharpe_ratio=cls._normalize_ratio_value(
                cls._read_value(source, "sharpe_ratio", 0.0),
                typed_metric_types.get("sharpe_ratio", MetricValueType.DECIMAL.value),
            ),
            sortino_ratio=cls._normalize_ratio_value(
                cls._read_value(source, "sortino_ratio", 0.0),
                typed_metric_types.get("sortino_ratio", MetricValueType.DECIMAL.value),
            ),
            calmar_ratio=cls._normalize_ratio_value(
                cls._read_value(source, "calmar_ratio", 0.0),
                typed_metric_types.get("calmar_ratio", MetricValueType.DECIMAL.value),
            ),
            win_rate=cls._normalize_ratio_value(
                cls._read_value(source, "win_rate", 0.0),
                typed_metric_types.get("win_rate", MetricValueType.DECIMAL.value),
            ),
            total_trades=int(cls._read_value(source, "total_trades", 0) or 0),
            winning_trades=int(cls._read_value(source, "winning_trades", 0) or 0),
            losing_trades=int(cls._read_value(source, "losing_trades", 0) or 0),
            annualization_factor=int(
                cls._read_value(source, "annualization_factor", DEFAULT_ANNUALIZATION_FACTOR)
                or DEFAULT_ANNUALIZATION_FACTOR
            ),
        )

    @classmethod
    def from_percentage_mapping(
        cls,
        metrics: Mapping[str, Any],
        *,
        win_rate_is_percentage: bool = True,
    ) -> "StandardizedMetricsSnapshot":
        """Build a canonical snapshot from legacy payloads that expose percent-based values."""
        win_rate_raw = float(metrics.get("win_rate", 0.0) or 0.0)
        return cls(
            initial_capital=float(metrics.get("initial_capital", metrics.get("initial_equity", 0.0)) or 0.0),
            final_capital=float(metrics.get("final_capital", metrics.get("final_equity", 0.0)) or 0.0),
            total_return=float(metrics.get("total_return", 0.0) or 0.0) / 100.0,
            annualized_return=float(
                metrics.get("annualized_return", metrics.get("annual_return", 0.0)) or 0.0
            ) / 100.0,
            max_drawdown=float(metrics.get("max_drawdown_amount", 0.0) or 0.0),
            max_drawdown_pct=float(
                metrics.get("max_drawdown_pct", metrics.get("max_drawdown", 0.0)) or 0.0
            ) / 100.0,
            volatility=float(metrics.get("volatility", 0.0) or 0.0) / 100.0,
            sharpe_ratio=float(metrics.get("sharpe_ratio", 0.0) or 0.0),
            sortino_ratio=float(metrics.get("sortino_ratio", 0.0) or 0.0),
            calmar_ratio=float(metrics.get("calmar_ratio", 0.0) or 0.0),
            win_rate=(win_rate_raw / 100.0) if win_rate_is_percentage else win_rate_raw,
            total_trades=int(metrics.get("total_trades", 0) or 0),
            winning_trades=int(metrics.get("winning_trades", 0) or 0),
            losing_trades=int(metrics.get("losing_trades", 0) or 0),
            annualization_factor=int(metrics.get("annualization_factor", DEFAULT_ANNUALIZATION_FACTOR) or DEFAULT_ANNUALIZATION_FACTOR),
        )

    def metric_type_names(self) -> Dict[str, str]:
        return {key: str(value) for key, value in self.metric_types.items()}

    @classmethod
    def percentage_payload_metric_types(cls) -> Dict[str, str]:
        return {
            "initial_capital": MetricValueType.ABSOLUTE_VALUE.value,
            "final_capital": MetricValueType.ABSOLUTE_VALUE.value,
            "final_equity": MetricValueType.ABSOLUTE_VALUE.value,
            "total_return": MetricValueType.PERCENTAGE.value,
            "annualized_return": MetricValueType.PERCENTAGE.value,
            "max_drawdown_amount": MetricValueType.ABSOLUTE_VALUE.value,
            "max_drawdown_pct": MetricValueType.PERCENTAGE.value,
            "volatility": MetricValueType.PERCENTAGE.value,
            "sharpe_ratio": MetricValueType.DECIMAL.value,
            "sortino_ratio": MetricValueType.DECIMAL.value,
            "calmar_ratio": MetricValueType.DECIMAL.value,
            "win_rate": MetricValueType.PERCENTAGE.value,
            "total_trades": MetricValueType.ABSOLUTE_VALUE.value,
            "winning_trades": MetricValueType.ABSOLUTE_VALUE.value,
            "losing_trades": MetricValueType.ABSOLUTE_VALUE.value,
            "annualization_factor": MetricValueType.ABSOLUTE_VALUE.value,
        }

    def to_percentage_payload(self, *, include_legacy_aliases: bool = False) -> Dict[str, Any]:
        """Convert canonical decimal metrics to legacy percent-based payloads."""
        payload: Dict[str, Any] = {
            "initial_capital": self.initial_capital,
            "final_capital": self.final_capital,
            "final_equity": self.final_capital,
            "total_return": self.total_return * 100.0,
            "annualized_return": self.annualized_return * 100.0,
            "max_drawdown_amount": self.max_drawdown,
            "max_drawdown_pct": self.max_drawdown_pct * 100.0,
            "volatility": self.volatility * 100.0,
            "sharpe_ratio": self.sharpe_ratio,
            "sortino_ratio": self.sortino_ratio,
            "calmar_ratio": self.calmar_ratio,
            "win_rate": self.win_rate * 100.0,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "annualization_factor": self.annualization_factor,
            "metric_types": self.percentage_payload_metric_types(),
        }
        if include_legacy_aliases:
            payload["annual_return"] = payload["annualized_return"]
            payload["metric_types"]["annual_return"] = MetricValueType.PERCENTAGE.value
        return payload

    @staticmethod
    def _read_value(source: Any, key: str, default: Any) -> Any:
        if isinstance(source, Mapping):
            return source.get(key, default)
        return getattr(source, key, default)

    @classmethod
    def _extract_mapping(cls, source: Any) -> Dict[str, Any]:
        keys = {
            "metric_types",
            "initial_capital",
            "initial_equity",
            "final_capital",
            "final_equity",
            "total_return",
            "annualized_return",
            "annual_return",
            "max_drawdown",
            "max_drawdown_amount",
            "max_drawdown_pct",
            "volatility",
            "sharpe_ratio",
            "sortino_ratio",
            "calmar_ratio",
            "win_rate",
            "total_trades",
            "winning_trades",
            "losing_trades",
            "annualization_factor",
        }
        return {key: cls._read_value(source, key, None) for key in keys if cls._read_value(source, key, None) is not None}

    @classmethod
    def _looks_like_percentage_source(cls, source: Any) -> bool:
        win_rate = cls._read_value(source, "win_rate", None)
        max_drawdown_pct = cls._read_value(source, "max_drawdown_pct", None)
        if win_rate is not None and abs(float(win_rate)) > 1.0:
            return True
        if max_drawdown_pct is not None and abs(float(max_drawdown_pct)) > 1.0:
            return True
        annualized_return = cls._read_value(source, "annualized_return", cls._read_value(source, "annual_return", None))
        if annualized_return is not None and abs(float(annualized_return)) > 5.0:
            return True
        return False

    @staticmethod
    def _normalize_ratio_value(raw_value: Any, metric_type: str) -> float:
        value = float(raw_value or 0.0)
        if metric_type == MetricValueType.PERCENTAGE.value:
            return value / 100.0
        return value

    @staticmethod
    def _normalize_absolute_value(raw_value: Any) -> float:
        return float(raw_value or 0.0)


class MetricsCalculator:
    """Shared metrics calculator used by replay, backtest, and virtual execution chains."""

    @staticmethod
    def calculate_from_returns(
        *,
        index: pd.Index,
        returns: Sequence[float] | pd.Series,
        initial_capital: float,
        total_trades: int = 0,
        winning_trades: int = 0,
        risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
        annualization_factor: int | None = None,
    ) -> StandardizedMetricsSnapshot:
        returns_series = pd.Series(returns, index=index, dtype=float).fillna(0.0)
        resolved_annualization_factor = annualization_factor or MetricsCalculator._resolve_annualization_factor(returns_series.index)
        equity_series = pd.Series(initial_capital, index=returns_series.index, dtype=float) * (1 + returns_series).cumprod()
        return MetricsCalculator._build_snapshot(
            equity_series=equity_series,
            returns_series=returns_series,
            initial_capital=initial_capital,
            annualization_factor=resolved_annualization_factor,
            total_trades=total_trades,
            winning_trades=winning_trades,
            risk_free_rate=risk_free_rate,
        )

    @staticmethod
    def calculate_from_equity_points(
        *,
        equity_points: Sequence[Mapping[str, Any] | tuple[Any, Any]],
        initial_capital: float,
        total_trades: int = 0,
        winning_trades: int = 0,
        risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
        annualization_factor: int | None = None,
    ) -> StandardizedMetricsSnapshot:
        equity_frame = MetricsCalculator._equity_frame_from_points(equity_points, initial_capital)
        if equity_frame.empty:
            return StandardizedMetricsSnapshot(
                initial_capital=initial_capital,
                final_capital=initial_capital,
                total_trades=total_trades,
                winning_trades=winning_trades,
                losing_trades=max(total_trades - winning_trades, 0),
            )

        resolved_annualization_factor = annualization_factor or MetricsCalculator._resolve_annualization_factor(equity_frame.index)
        returns_series = equity_frame["equity"].pct_change().fillna(0.0)
        return MetricsCalculator._build_snapshot(
            equity_series=equity_frame["equity"],
            returns_series=returns_series,
            initial_capital=initial_capital,
            annualization_factor=resolved_annualization_factor,
            total_trades=total_trades,
            winning_trades=winning_trades,
            risk_free_rate=risk_free_rate,
        )

    @staticmethod
    def _build_snapshot(
        *,
        equity_series: pd.Series,
        returns_series: pd.Series,
        initial_capital: float,
        annualization_factor: int,
        total_trades: int,
        winning_trades: int,
        risk_free_rate: float,
    ) -> StandardizedMetricsSnapshot:
        if equity_series.empty:
            return StandardizedMetricsSnapshot(
                initial_capital=initial_capital,
                final_capital=initial_capital,
                total_trades=total_trades,
                winning_trades=winning_trades,
                losing_trades=max(total_trades - winning_trades, 0),
                annualization_factor=annualization_factor,
            )

        final_capital = float(equity_series.iloc[-1])
        total_return = (final_capital / initial_capital - 1) if initial_capital > 0 else 0.0
        observed_periods = max(len(returns_series) - 1, 0)
        annualized_return = MetricsCalculator._annualize_return_ratio(
            total_return_ratio=total_return,
            periods_observed=observed_periods,
            annualization_factor=annualization_factor,
        )

        rolling_peak = equity_series.cummax()
        drawdown_amount = (rolling_peak - equity_series).clip(lower=0.0)
        drawdown_pct = (drawdown_amount / rolling_peak.replace(0.0, pd.NA)).fillna(0.0)
        max_drawdown = float(drawdown_amount.max()) if not drawdown_amount.empty else 0.0
        max_drawdown_pct = float(drawdown_pct.max()) if not drawdown_pct.empty else 0.0

        volatility = MetricsCalculator._annualized_volatility(returns_series, annualization_factor)
        sharpe_ratio = annualize_sharpe(returns_series, annualization_factor, risk_free_rate)
        downside_deviation = MetricsCalculator._downside_deviation(returns_series, annualization_factor, risk_free_rate)
        sortino_ratio = (
            float((annualized_return - risk_free_rate) / downside_deviation)
            if downside_deviation > 0
            else 0.0
        )
        calmar_ratio = float(annualized_return / max_drawdown_pct) if max_drawdown_pct > 0 else 0.0

        total_trades = int(total_trades)
        winning_trades = int(winning_trades)
        losing_trades = max(total_trades - winning_trades, 0)
        win_rate = float(winning_trades / total_trades) if total_trades > 0 else 0.0

        return StandardizedMetricsSnapshot(
            initial_capital=float(initial_capital),
            final_capital=final_capital,
            total_return=float(total_return),
            annualized_return=float(annualized_return),
            max_drawdown=max_drawdown,
            max_drawdown_pct=max_drawdown_pct,
            volatility=float(volatility),
            sharpe_ratio=float(sharpe_ratio),
            sortino_ratio=float(sortino_ratio),
            calmar_ratio=float(calmar_ratio),
            win_rate=win_rate,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            annualization_factor=annualization_factor,
        )

    @staticmethod
    def _equity_frame_from_points(
        equity_points: Sequence[Mapping[str, Any] | tuple[Any, Any]],
        initial_capital: float,
    ) -> pd.DataFrame:
        normalized_points = []
        for point in equity_points:
            if isinstance(point, Mapping):
                timestamp = point.get("timestamp") or point.get("t") or point.get("time")
                equity = point.get("equity", point.get("v", point.get("total_equity", initial_capital)))
            else:
                timestamp, equity = point
            normalized_points.append({"timestamp": timestamp, "equity": float(equity)})

        if not normalized_points:
            return pd.DataFrame(columns=["equity"])

        equity_frame = pd.DataFrame(normalized_points)
        equity_frame["timestamp"] = pd.to_datetime(equity_frame["timestamp"], errors="coerce", utc=True)
        equity_frame = equity_frame.dropna(subset=["timestamp"]).drop_duplicates(subset=["timestamp"], keep="last")
        equity_frame = equity_frame.sort_values("timestamp").set_index("timestamp")
        if equity_frame.empty:
            return pd.DataFrame(columns=["equity"])
        return equity_frame

    @staticmethod
    def _resolve_annualization_factor(index: pd.Index) -> int:
        if isinstance(index, pd.DatetimeIndex) and len(index) > 1:
            try:
                return infer_annualization_factor(index)
            except ValueError:
                logger.warning("Failed to infer annualization factor from index; using default %s.", DEFAULT_ANNUALIZATION_FACTOR)
        return DEFAULT_ANNUALIZATION_FACTOR

    @staticmethod
    def _annualize_return_ratio(total_return_ratio: float, periods_observed: int, annualization_factor: int) -> float:
        if periods_observed <= 0 or annualization_factor <= 0:
            return 0.0
        if total_return_ratio <= -1.0:
            return -1.0
        return float((1 + total_return_ratio) ** (annualization_factor / periods_observed) - 1)

    @staticmethod
    def _annualized_volatility(returns: pd.Series, annualization_factor: int) -> float:
        if returns.empty or len(returns) < 2 or annualization_factor <= 0:
            return 0.0
        std = float(returns.std(ddof=1))
        if std <= 0 or math.isnan(std):
            return 0.0
        return float(std * math.sqrt(annualization_factor))

    @staticmethod
    def _downside_deviation(returns: pd.Series, annualization_factor: int, risk_free_rate: float) -> float:
        if returns.empty or len(returns) < 2 or annualization_factor <= 0:
            return 0.0
        risk_free_per_period = risk_free_rate / annualization_factor
        downside_excess = (returns - risk_free_per_period).clip(upper=0.0)
        downside_variance = float((downside_excess.pow(2)).mean())
        if downside_variance <= 0 or math.isnan(downside_variance):
            return 0.0
        return float(math.sqrt(downside_variance) * math.sqrt(annualization_factor))
