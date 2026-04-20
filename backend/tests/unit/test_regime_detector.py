import math
from datetime import datetime, timedelta, timezone

import pandas as pd

from app.services.dynamic_selection.regime_detector import RegimeDetector


def _build_price_frame(closes: list[float]) -> pd.DataFrame:
    base_time = datetime(2025, 1, 1, tzinfo=timezone.utc)
    index = [base_time + timedelta(hours=4 * idx) for idx in range(len(closes))]
    return pd.DataFrame(
        {
            "open": closes,
            "high": [price * 1.01 for price in closes],
            "low": [price * 0.99 for price in closes],
            "close": closes,
            "volume": [1000.0] * len(closes),
        },
        index=index,
    )


def test_regime_detector_identifies_trend_up():
    closes = [100 + idx * 1.2 for idx in range(80)]
    result = RegimeDetector().detect(_build_price_frame(closes))
    assert result.regime == "trend_up"


def test_regime_detector_identifies_range():
    closes = [100 + math.sin(idx / 2.0) * 2 for idx in range(80)]
    result = RegimeDetector().detect(_build_price_frame(closes))
    assert result.regime == "range"


def test_regime_detector_identifies_high_vol():
    closes = [100, 120, 85, 125, 80, 130, 78, 128] * 10
    result = RegimeDetector().detect(_build_price_frame(closes))
    assert result.regime == "high_vol"
