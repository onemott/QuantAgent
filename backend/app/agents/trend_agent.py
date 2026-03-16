"""
Trend Agent — Analyzes price momentum and directional trend using SMA/EMA.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

from app.agents.base_agent import BaseAgent, SignalType
from app.services.binance_service import binance_service
from app.services.indicators import sma, ema, macd

logger = logging.getLogger(__name__)


class TrendAgent(BaseAgent):
    """Trend following specialist: identifies primary trend direction."""

    @property
    def agent_id(self) -> str:
        return "trend"

    @property
    def agent_name(self) -> str:
        return "趋势跟踪 Agent"

    @property
    def system_prompt(self) -> str:
        return """You are a Trend Following Specialist. Your role is to identify the primary
market trend using price action, moving averages, and momentum indicators.

IMPORTANT RULES:
1. Respond ENTIRELY in Chinese (中文).
2. Use markdown formatting with clear sections.
3. End your analysis with a clear signal: **BUY** / **SELL** / **WAIT**
4. Assign a confidence percentage (e.g., "置信度: 75%").
"""

    async def observe(self, symbol: str, interval: str = "1h") -> Dict[str, Any]:
        """Fetch K-lines and compute trend indicators."""
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
            df = sma(df, 10);  df = sma(df, 30)
            df = ema(df, 12);  df = ema(df, 26)
            df = macd(df)
            last = df.iloc[-1]
            indicators = {
                "sma_10":     round(float(last.get("sma_10", 0)), 2),
                "sma_30":     round(float(last.get("sma_30", 0)), 2),
                "ema_12":     round(float(last.get("ema_12", 0)), 2),
                "ema_26":     round(float(last.get("ema_26", 0)), 2),
                "macd_dif":   round(float(last.get("macd_dif", 0)), 4),
                "macd_dea":   round(float(last.get("macd_dea", 0)), 4),
                "macd_hist":  round(float(last.get("macd_hist", 0)), 4),
            }
        except Exception as e:
            logger.warning(f"[trend] Indicator calculation failed: {e}")

        recent = [{"t": k.timestamp.strftime("%m-%d %H:%M"), "c": k.close, "v": k.volume}
                  for k in klines[-15:]]

        return {"symbol": symbol, "price": price, "indicators": indicators, "recent": recent}

    def build_prompt(self, context: Dict[str, Any], memory_ctx: str = "") -> str:
        sym = context["symbol"]
        price = context["price"]
        ind = context["indicators"]
        recent = context.get("recent", [])
        mem_section = f"\n{memory_ctx}\n" if memory_ctx else ""

        return f"""
## 趋势分析任务: {sym}
当前价格: **${price:,.4f}**
{mem_section}
### 技术指标
| 指标 | 数值 |
|------|------|
| SMA(10) | {ind.get('sma_10', 'N/A')} |
| SMA(30) | {ind.get('sma_30', 'N/A')} |
| EMA(12) | {ind.get('ema_12', 'N/A')} |
| EMA(26) | {ind.get('ema_26', 'N/A')} |
| MACD DIF | {ind.get('macd_dif', 'N/A')} |
| MACD DEA | {ind.get('macd_dea', 'N/A')} |
| MACD 柱 | {ind.get('macd_hist', 'N/A')} |

### 近期价格 (最近15根K线)
{json.dumps(recent, ensure_ascii=False, indent=2)}

### 分析要求
1. 判断主趋势方向（上涨/下跌/横盘）
2. 识别关键支撑/阻力位
3. 均线多空排列状态
4. MACD 金叉/死叉信号
5. 给出交易信号: **BUY** / **SELL** / **WAIT** 及置信度
"""
