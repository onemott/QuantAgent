"""
Mean Reversion Agent — Identifies overbought/oversold conditions via RSI + Bollinger Bands.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from app.agents.base_agent import BaseAgent, SignalType
from app.services.binance_service import binance_service
from app.services.indicators import rsi, bollinger_bands

logger = logging.getLogger(__name__)


class MeanReversionAgent(BaseAgent):
    """Mean reversion specialist: looks for reversal setups at extremes."""

    @property
    def agent_id(self) -> str:
        return "mean_reversion"

    @property
    def agent_name(self) -> str:
        return "均值回归 Agent"

    @property
    def system_prompt(self) -> str:
        return """You are a Mean Reversion Specialist. You identify overbought/oversold
conditions using RSI and Bollinger Bands to find high-probability reversal setups.

IMPORTANT RULES:
1. Respond ENTIRELY in Chinese (中文).
2. Use markdown formatting.
3. End with a clear signal: **LONG_REVERSAL** / **SHORT_REVERSAL** / **WAIT**
4. Assign a confidence percentage.
"""

    async def observe(self, symbol: str, interval: str = "1h") -> Dict[str, Any]:
        """Fetch K-lines and compute RSI + Bollinger Bands."""
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
            df = rsi(df, 14)
            df = bollinger_bands(df, 20, 2.0)
            last = df.iloc[-1]
            indicators = {
                "rsi_14":     round(float(last.get("rsi_14", 50)), 2),
                "boll_upper": round(float(last.get("boll_upper", 0)), 2),
                "boll_mid":   round(float(last.get("boll_mid", 0)), 2),
                "boll_lower": round(float(last.get("boll_lower", 0)), 2),
                "boll_pct_b": round(float(last.get("boll_pct_b", 0.5)), 4),
                "boll_width": round(float(last.get("boll_width", 0)), 4),
            }
        except Exception as e:
            logger.warning(f"[mean_reversion] Indicator calculation failed: {e}")

        return {"symbol": symbol, "price": price, "indicators": indicators}

    def build_prompt(self, context: Dict[str, Any], memory_ctx: str = "") -> str:
        sym   = context["symbol"]
        price = context["price"]
        ind   = context["indicators"]
        mem_section = f"\n{memory_ctx}\n" if memory_ctx else ""

        rsi_val  = ind.get("rsi_14", 50)
        pct_b    = ind.get("boll_pct_b", 0.5)
        rsi_state  = "🔴 超买" if rsi_val > 70 else ("🟢 超卖" if rsi_val < 30 else "⚪ 中性")
        boll_state = "🔴 触碰上轨" if pct_b > 0.95 else ("🟢 触碰下轨" if pct_b < 0.05 else "⚪ 带内")

        return f"""
## 均值回归分析任务: {sym}
当前价格: **${price:,.4f}**
{mem_section}
### 技术指标
| 指标 | 数值 | 状态 |
|------|------|------|
| RSI(14) | {rsi_val} | {rsi_state} |
| 布林上轨 | {ind.get('boll_upper', 'N/A')} | — |
| 布林中轨 | {ind.get('boll_mid', 'N/A')} | — |
| 布林下轨 | {ind.get('boll_lower', 'N/A')} | — |
| %B 位置 | {pct_b:.3f} | {boll_state} |
| 布林带宽 | {ind.get('boll_width', 'N/A')} | — |

### 分析要求
1. 判断 RSI 超买/超卖状态及背离可能性
2. 评估价格在布林带内的位置
3. 判断是否存在均值回归机会
4. 给出信号: **LONG_REVERSAL** / **SHORT_REVERSAL** / **WAIT** 及置信度
"""
