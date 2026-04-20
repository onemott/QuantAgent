from dataclasses import dataclass

import pandas as pd


@dataclass
class RegimeDetectionResult:
    regime: str
    adx_value: float
    volatility_percentile: float
    directional_consistency: float
    recent_return: float
    reason: str


class RegimeDetector:
    def __init__(
        self,
        *,
        adx_period: int = 14,
        volatility_window: int = 20,
        direction_window: int = 20,
        trend_adx_threshold: float = 25.0,
        trend_consistency_threshold: float = 0.55,
        high_vol_percentile_threshold: float = 0.8,
        high_vol_consistency_ceiling: float = 0.45,
        min_trend_return: float = 0.02,
    ):
        self.adx_period = adx_period
        self.volatility_window = volatility_window
        self.direction_window = direction_window
        self.trend_adx_threshold = trend_adx_threshold
        self.trend_consistency_threshold = trend_consistency_threshold
        self.high_vol_percentile_threshold = high_vol_percentile_threshold
        self.high_vol_consistency_ceiling = high_vol_consistency_ceiling
        self.min_trend_return = min_trend_return

    def detect(self, df: pd.DataFrame) -> RegimeDetectionResult:
        normalized = self._ensure_ohlcv(df)
        adx_value = self._calculate_adx(normalized, self.adx_period)
        volatility_percentile = self._calculate_volatility_percentile(normalized)
        directional_consistency, recent_return = self._calculate_direction_signal(normalized)

        if (
            volatility_percentile >= self.high_vol_percentile_threshold
            and directional_consistency <= self.high_vol_consistency_ceiling
        ):
            return RegimeDetectionResult(
                regime="high_vol",
                adx_value=adx_value,
                volatility_percentile=volatility_percentile,
                directional_consistency=directional_consistency,
                recent_return=recent_return,
                reason="近期波动处于样本高分位，且方向一致性偏弱",
            )

        if (
            adx_value >= self.trend_adx_threshold
            and directional_consistency >= self.trend_consistency_threshold
            and abs(recent_return) >= self.min_trend_return
        ):
            regime = "trend_up" if recent_return >= 0 else "trend_down"
            return RegimeDetectionResult(
                regime=regime,
                adx_value=adx_value,
                volatility_percentile=volatility_percentile,
                directional_consistency=directional_consistency,
                recent_return=recent_return,
                reason="ADX 与收益方向一致性同时满足趋势阈值",
            )

        return RegimeDetectionResult(
            regime="range",
            adx_value=adx_value,
            volatility_percentile=volatility_percentile,
            directional_consistency=directional_consistency,
            recent_return=recent_return,
            reason="未满足趋势或高波动判定，按震荡处理",
        )

    @staticmethod
    def _ensure_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
        required_cols = ["high", "low", "close"]
        missing = [column for column in required_cols if column not in df.columns]
        if missing:
            raise ValueError(f"regime detector requires columns: {missing}")
        normalized = df.copy().sort_index()
        if not isinstance(normalized.index, pd.DatetimeIndex):
            normalized.index = pd.to_datetime(normalized.index, utc=True)
        return normalized

    @staticmethod
    def _calculate_adx(df: pd.DataFrame, period: int) -> float:
        if len(df) < period + 1:
            return 20.0

        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)

        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm < 0] = 0
        plus_dm[plus_dm <= minus_dm] = 0
        minus_dm[minus_dm <= plus_dm] = 0

        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        atr = true_range.ewm(alpha=1 / period, min_periods=period).mean()
        plus_di = 100 * (plus_dm.ewm(alpha=1 / period, min_periods=period).mean() / atr.replace(0, pd.NA))
        minus_di = 100 * (minus_dm.ewm(alpha=1 / period, min_periods=period).mean() / atr.replace(0, pd.NA))
        dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, pd.NA)) * 100
        adx = dx.ewm(alpha=1 / period, min_periods=period).mean().dropna()
        if adx.empty:
            return 20.0
        return float(adx.iloc[-1])

    def _calculate_volatility_percentile(self, df: pd.DataFrame) -> float:
        returns = df["close"].astype(float).pct_change().dropna()
        if len(returns) < max(5, self.volatility_window // 2):
            return 0.5

        rolling_vol = returns.rolling(
            window=self.volatility_window,
            min_periods=max(5, self.volatility_window // 2),
        ).std().dropna()
        if rolling_vol.empty:
            return 0.5

        current_vol = float(rolling_vol.iloc[-1])
        return float((rolling_vol <= current_vol).mean())

    def _calculate_direction_signal(self, df: pd.DataFrame) -> tuple[float, float]:
        closes = df["close"].astype(float)
        returns = closes.pct_change().dropna()
        if returns.empty:
            return 0.0, 0.0

        recent_returns = returns.tail(self.direction_window)
        signs = recent_returns.apply(lambda value: 1 if value > 0 else (-1 if value < 0 else 0))
        non_zero_signs = signs[signs != 0]
        directional_consistency = abs(float(non_zero_signs.mean())) if not non_zero_signs.empty else 0.0

        lookback = min(self.direction_window, len(closes) - 1)
        if lookback <= 0:
            return directional_consistency, 0.0
        recent_return = float(closes.iloc[-1] / closes.iloc[-1 - lookback] - 1)
        return directional_consistency, recent_return
