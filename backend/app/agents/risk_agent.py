"""
Risk Agent — Monitors volatility and assesses overall portfolio risk using ATR.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from app.agents.base_agent import BaseAgent, SignalType
from app.services.binance_service import binance_service
from app.services.indicators import atr, rsi

logger = logging.getLogger(__name__)


class RiskAgent(BaseAgent):
    """Risk management officer: evaluates volatility, leverage, and stop-loss levels."""

    @property
    def agent_id(self) -> str:
        return "risk"

    @property
    def agent_name(self) -> str:
        return "风险管理 Agent"

    @property
    def system_prompt(self) -> str:
        return """You are a Risk Management Officer. Your job is to assess current market
volatility, recommend appropriate position sizing, and identify risk levels.

IMPORTANT RULES:
1. Respond ENTIRELY in Chinese (中文).
2. Use markdown formatting.
3. End with a risk verdict: **LOW RISK** / **MEDIUM RISK** / **HIGH RISK** / **EXTREME RISK**
4. Always recommend a specific stop-loss distance and max leverage.
"""

    async def observe(self, symbol: str, interval: str = "1h") -> Dict[str, Any]:
        """Fetch K-lines and compute ATR-based volatility metrics."""
        import pandas as pd
        klines = await binance_service.get_klines(symbol, interval, limit=100)
        price  = await binance_service.get_price(symbol)

        df_data = [
            {"timestamp": k.timestamp, "open": k.open, "high": k.high,
             "low": k.low, "close": k.close, "volume": k.volume}
            for k in klines
        ]
        df = pd.DataFrame(df_data)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df.set_index("timestamp", inplace=True)
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)

        indicators: Dict[str, Any] = {}
        try:
            df = atr(df, 14)
            df = rsi(df, 14)
            last = df.iloc[-1]
            atr_val = float(last.get("atr_14", 0))
            atr_pct = (atr_val / price * 100) if price > 0 else 0.0
            indicators = {
                "atr_14":      round(atr_val, 4),
                "atr_pct":     round(atr_pct, 3),      # ATR as % of price
                "rsi_14":      round(float(last.get("rsi_14", 50)), 2),
                "stop_1x_atr": round(price - atr_val, 2),
                "stop_2x_atr": round(price - 2 * atr_val, 2),
                "stop_3x_atr": round(price - 3 * atr_val, 2),
            }
        except Exception as e:
            logger.warning(f"[risk] Indicator calculation failed: {e}")

        return {"symbol": symbol, "price": price, "indicators": indicators}

    def build_prompt(self, context: Dict[str, Any], memory_ctx: str = "") -> str:
        sym   = context["symbol"]
        price = context["price"]
        ind   = context["indicators"]
        mem_section = f"\n{memory_ctx}\n" if memory_ctx else ""

        atr_pct = ind.get("atr_pct", 0)
        risk_level = (
            "极高风险" if atr_pct > 5 else
            "高风险"   if atr_pct > 3 else
            "中等风险" if atr_pct > 1.5 else
            "低风险"
        )

        return f"""
## 风险评估任务: {sym}
当前价格: **${price:,.4f}**
{mem_section}
### 波动率指标
| 指标 | 数值 |
|------|------|
| ATR(14) | {ind.get('atr_14', 'N/A')} |
| ATR% (占价格比) | {atr_pct:.3f}% → 初判: **{risk_level}** |
| RSI(14) | {ind.get('rsi_14', 'N/A')} |
| 止损位(1×ATR) | ${ind.get('stop_1x_atr', 'N/A')} |
| 止损位(2×ATR) | ${ind.get('stop_2x_atr', 'N/A')} |
| 止损位(3×ATR) | ${ind.get('stop_3x_atr', 'N/A')} |

### 分析要求
1. 评估当前市场波动性级别
2. 建议合适的仓位大小（占账户 %）
3. 推荐最大杠杆倍数
4. 基于 ATR 给出最优止损距离
5. 综合给出风险等级: **LOW RISK** / **MEDIUM RISK** / **HIGH RISK** / **EXTREME RISK**
"""

    def parse_signal(self, text: str):
        """Override: risk agent uses risk levels instead of trade signals."""
        from app.agents.base_agent import SignalType
        text_upper = text.upper()
        if "EXTREME RISK" in text_upper or "极高风险" in text:
            return SignalType.WAIT, 0.9
        elif "HIGH RISK" in text_upper or "高风险" in text:
            return SignalType.WAIT, 0.75
        elif "LOW RISK" in text_upper or "低风险" in text:
            return SignalType.HOLD, 0.7
        else:
            return SignalType.HOLD, 0.6
