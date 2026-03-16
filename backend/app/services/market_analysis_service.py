"""
Market Analysis Service powered by LLM
"""

from app.services.llm.base import LLMFactory
from app.services.binance_service import binance_service
from app.services.embedding_service import embedding_service
from app.models.market_data import KlineData
from typing import List, AsyncGenerator, Dict, Any, Optional
import json
import logging
import pandas as pd
from app.services.indicators import rsi, bollinger_bands, atr
from app.services.database import redis_get, redis_set, get_db
from app.models.db_models import AgentMemory
from sqlalchemy import select

logger = logging.getLogger(__name__)

# 每个 agent+symbol 最多保留的历史记忆条数
MEMORY_WINDOW = 5
MEMORY_TTL    = 3600 * 6   # Redis 缓存 6 小时


class BaseAgentService:
    def __init__(self, provider_name: str = None):
        print(f"Creating LLM provider: {provider_name}")
        self.llm = LLMFactory.create_provider(provider_name)
        print(f"LLM provider created: {self.llm}")

    # ── 记忆层：从 Redis 读取历史摘要 ──────────────────────────────────────
    async def _load_memory(self, agent_type: str, symbol: str, current_embedding: List[float] = None) -> str:
        """
        加载最近 MEMORY_WINDOW 条分析摘要，拼接成上下文字符串。
        优先尝试向量检索（RAG），如果无 embedding 或检索失败，则回退到按时间倒序。
        """
        # 1. RAG 向量检索
        if current_embedding and len(current_embedding) > 0:
            try:
                async with get_db() as session:
                    stmt = (
                        select(AgentMemory)
                        .where(AgentMemory.agent_type == agent_type)
                        .where(AgentMemory.symbol == symbol)
                        .where(AgentMemory.market_state_embedding.isnot(None))
                        .order_by(AgentMemory.market_state_embedding.cosine_distance(current_embedding))
                        .limit(3)
                    )
                    result = await session.execute(stmt)
                    rag_rows = result.scalars().all()
                    
                    if rag_rows:
                        rag_memories = []
                        for row in rag_rows:
                            pnl_str = f" | 盈亏: {row.outcome_pnl:.2f}%" if row.outcome_pnl is not None else ""
                            rag_memories.append(
                                f"- [相似历史] {row.created_at.strftime('%Y-%m-%d')}: {row.summary[:100]}... "
                                f"(信号: {row.signal}, 置信度: {row.confidence:.0%}{pnl_str})"
                            )
                        return "\n".join(["[History Lesson: 基于相似行情的历史回顾]", *rag_memories])
            except Exception as e:
                logger.warning(f"RAG search failed: {e}")
                # Fallback to time-based

        # 2. Redis/DB 时间倒序回退
        redis_key = f"agent_memory:{agent_type}:{symbol}"
        cached = await redis_get(redis_key)
        if cached:
            memories: List[Dict] = cached
        else:
            try:
                async with get_db() as session:
                    stmt = (
                        select(AgentMemory)
                        .where(AgentMemory.agent_type == agent_type)
                        .where(AgentMemory.symbol == symbol)
                        .order_by(AgentMemory.created_at.desc())
                        .limit(MEMORY_WINDOW)
                    )
                    result = await session.execute(stmt)
                    rows = result.scalars().all()
                memories = [
                    {
                        "summary":    row.summary[:300],
                        "signal":     row.signal,
                        "confidence": row.confidence,
                        "time":       row.created_at.strftime("%Y-%m-%d %H:%M") if row.created_at else "",
                    }
                    for row in reversed(rows)
                ]
                await redis_set(redis_key, memories, ttl=MEMORY_TTL)
            except Exception as e:
                logger.warning(f"Failed to load agent memory: {e}")
                memories = []

        if not memories:
            return ""

        lines = ["[历史分析记忆（最近{}条）]".format(len(memories))]
        for m in memories:
            sig_str = f" | 信号: {m['signal']}" if m.get("signal") else ""
            conf_str = f" | 置信度: {m['confidence']:.0%}" if m.get("confidence") else ""
            lines.append(f"- [{m.get('time','')}]{sig_str}{conf_str}: {m.get('summary','')}")
        return "\n".join(lines)

    async def _save_memory(
        self,
        agent_type: str,
        symbol: str,
        summary: str,
        signal: Optional[str] = None,
        confidence: Optional[float] = None,
        embedding: Optional[List[float]] = None,
        entry_price: Optional[float] = None,
    ) -> None:
        """
        保存本次分析摘要到 PostgreSQL，并清除 Redis 缓存使下次重新加载。
        """
        try:
            async with get_db() as session:
                entry = AgentMemory(
                    agent_type=agent_type,
                    symbol=symbol,
                    summary=summary[:500],
                    signal=signal,
                    confidence=confidence,
                    market_state_embedding=embedding if embedding and len(embedding) > 0 else None,
                    entry_price=entry_price
                )
                session.add(entry)
            # 清除 Redis 缓存，下次调用重新加载
            redis_key = f"agent_memory:{agent_type}:{symbol}"
            from app.services.database import redis_delete
            await redis_delete(redis_key)
        except Exception as e:
            logger.warning(f"Failed to save agent memory: {e}")

    # ── 市场数据准备 ────────────────────────────────────────────────────────
    async def _prepare_analysis_inputs(self, symbol: str, interval: str = "1h"):
        """Fetch market data and build prompt/system_prompt. Returns (prompt, system_prompt, embedding, current_price)."""
        klines = await binance_service.get_klines(symbol, interval, limit=100)
        current_price = await binance_service.get_price(symbol)

        df_data = [
            {
                "timestamp": k.timestamp,
                "open": k.open,
                "high": k.high,
                "low": k.low,
                "close": k.close,
                "volume": k.volume
            }
            for k in klines
        ]
        df = pd.DataFrame(df_data)

        if not df.empty:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df.set_index('timestamp', inplace=True)
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = df[col].astype(float)

        # Generate Context Embedding (RAG)
        context_str = f"Symbol: {symbol}, Price: {current_price}"
        if not df.empty and len(df) > 20:
            # Add simple indicators to context string for similarity search
            try:
                # Simple RSI approx
                delta = df['close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                rsi_val = 100 - (100 / (1 + rs)).iloc[-1]
                context_str += f", RSI: {rsi_val:.2f}"
                
                # Simple BB approx
                sma = df['close'].rolling(window=20).mean()
                std = df['close'].rolling(window=20).std()
                upper = sma + (std * 2)
                lower = sma - (std * 2)
                pct_b = (df['close'] - lower) / (upper - lower)
                context_str += f", BB%B: {pct_b.iloc[-1]:.2f}"
            except Exception:
                pass
        
        context_embedding = await embedding_service.get_embedding(context_str)

        # 加载历史记忆 (Pass embedding for RAG)
        memory_ctx = await self._load_memory(self._agent_type(), symbol, context_embedding)

        prompt = self._build_prompt(symbol, current_price, klines, df, memory_ctx)
        system_prompt = self._get_system_prompt()
        return prompt, system_prompt, context_embedding, current_price

    def _agent_type(self) -> str:
        """返回 agent 类型标识，子类可重写。"""
        return "base"

    async def analyze(self, symbol: str, interval: str = "1h") -> str:
        if not self.llm:
            return "Error: LLM provider not configured correctly. Please check your API keys."

        try:
            prompt, system_prompt, embedding, current_price = await self._prepare_analysis_inputs(symbol, interval)
            analysis = await self.llm.generate(prompt, system_prompt=system_prompt, temperature=0.7)
            # 保存记忆
            summary = analysis[:400] if analysis else ""
            signal = self._extract_signal(analysis)
            # Rough confidence estimate
            confidence = 0.8 if signal else 0.6
            
            await self._save_memory(
                self._agent_type(), 
                symbol, 
                summary, 
                signal=signal, 
                confidence=confidence,
                embedding=embedding,
                entry_price=current_price
            )
            return analysis
        except Exception as e:
            logger.error(f"Analysis failed: {e}")
            import traceback
            traceback.print_exc()
            return f"Error: Analysis failed - {str(e)}"

    async def analyze_stream(self, symbol: str, interval: str = "1h") -> AsyncGenerator[str, None]:
        """Stream analysis output chunk by chunk via the LLM provider's stream() method."""
        accumulated = ""
        embedding = []
        current_price = 0.0
        try:
            prompt, system_prompt, embedding, current_price = await self._prepare_analysis_inputs(symbol, interval)
            async for chunk in self.llm.stream(prompt, system_prompt=system_prompt, temperature=0.7):
                accumulated += chunk
                yield chunk
        except Exception as e:
            logger.error(f"Stream analysis failed: {e}")
            import traceback
            traceback.print_exc()
            yield f"Error: Stream analysis failed - {str(e)}"
        finally:
            # 流结束后保存记忆
            if accumulated:
                summary = accumulated[:400]
                signal = self._extract_signal(accumulated)
                confidence = 0.8 if signal else 0.6
                try:
                    await self._save_memory(
                        self._agent_type(), 
                        symbol, 
                        summary, 
                        signal=signal, 
                        confidence=confidence,
                        embedding=embedding,
                        entry_price=current_price
                    )
                except Exception as e:
                    logger.warning(f"Failed to save stream memory: {e}")

    def _extract_signal(self, text: str) -> Optional[str]:
        """从 LLM 输出中提取交易信号关键词。"""
        if not text:
            return None
        text_upper = text.upper()
        for sig in ["LONG_REVERSAL", "SHORT_REVERSAL", "BUY", "SELL", "WAIT", "HOLD"]:
            if sig in text_upper:
                return sig
        return None

    def _get_system_prompt(self) -> str:
        return "You are a crypto trading assistant."

    def _build_prompt(
        self,
        symbol: str,
        current_price: float,
        klines: List[KlineData],
        df: pd.DataFrame,
        memory_ctx: str = "",
    ) -> str:
        raise NotImplementedError

    # Keep for backward compatibility if needed, but analyze() is preferred
    async def analyze_market(self, symbol: str = "BTC/USDT", interval: str = "1h") -> str:
        return await self.analyze(symbol, interval)


class TrendAgentService(BaseAgentService):
    def _agent_type(self) -> str:
        return "trend"

    def _get_system_prompt(self) -> str:
        return """You are a Trend Following Specialist. Analyze market trends using price action and volume.

IMPORTANT: You MUST respond in Chinese (中文). All analysis, explanations, and conclusions should be written in Chinese.
Use markdown format for your response with clear headings and bullet points."""

    def _build_prompt(
        self,
        symbol: str,
        current_price: float,
        klines: List[KlineData],
        df: pd.DataFrame,
        memory_ctx: str = "",
    ) -> str:
        # Simplify kline data for LLM
        data_summary = []
        # Use last 15 candles for prompt context
        recent_klines = klines[-15:] if len(klines) >= 15 else klines

        for k in recent_klines:
            data_summary.append({
                "time": k.timestamp.strftime("%Y-%m-%d %H:%M"),
                "o": k.open,
                "h": k.high,
                "l": k.low,
                "c": k.close,
                "v": k.volume
            })

        memory_section = f"\n{memory_ctx}\n" if memory_ctx else ""

        prompt = f"""
        Trend Analysis for {symbol}
        Current Price: {current_price}
        {memory_section}
        Recent Market Data (Last {len(recent_klines)} candles):
        {json.dumps(data_summary, indent=2)}

        Task:
        1. Identify the primary trend (Uptrend/Downtrend/Sideways).
        2. Identify key support and resistance levels.
        3. Analyze volume patterns confirming the trend.
        4. Provide a trading signal: BUY / SELL / WAIT.

        Output concisely in markdown.
        """
        return prompt


class MeanReversionAgentService(BaseAgentService):
    def _agent_type(self) -> str:
        return "mean_reversion"

    def _get_system_prompt(self) -> str:
        return """You are a Mean Reversion Specialist. Look for overbought/oversold conditions using RSI and Bollinger Bands.

IMPORTANT: You MUST respond in Chinese (中文). All analysis, explanations, and conclusions should be written in Chinese.
Use markdown format for your response with clear headings and bullet points."""

    def _build_prompt(
        self,
        symbol: str,
        current_price: float,
        klines: List[KlineData],
        df: pd.DataFrame,
        memory_ctx: str = "",
    ) -> str:
        # Calculate Indicators
        rsi_val = 50
        bb_upper = bb_lower = bb_pct = 0

        if not df.empty and len(df) > 20:
            try:
                df_rsi = rsi(df, period=14)
                df_bb = bollinger_bands(df_rsi, period=20, std_dev=2.0)

                last_row = df_bb.iloc[-1]
                rsi_val = last_row.get('rsi_14', 50)
                bb_upper = last_row.get('boll_upper', 0)
                bb_lower = last_row.get('boll_lower', 0)
                bb_pct = last_row.get('boll_pct_b', 0.5)
            except Exception as e:
                logger.error(f"Indicator calculation failed: {e}")

        memory_section = f"\n{memory_ctx}\n" if memory_ctx else ""

        prompt = f"""
        Mean Reversion Analysis for {symbol}
        Current Price: {current_price}
        {memory_section}
        Technical Indicators:
        - RSI (14): {rsi_val:.2f}
        - Bollinger Upper: {bb_upper:.2f}
        - Bollinger Lower: {bb_lower:.2f}
        - %B (Position in Band): {bb_pct:.2f}

        Task:
        1. Assess if the asset is Overbought (RSI > 70) or Oversold (RSI < 30).
        2. Check if price is at Bollinger Band extremes.
        3. Look for potential reversal signals.
        4. Provide a trading signal: LONG_REVERSAL / SHORT_REVERSAL / WAIT.

        Output concisely in markdown.
        """
        return prompt


class RiskAgentService(BaseAgentService):
    def _agent_type(self) -> str:
        return "risk"

    def _get_system_prompt(self) -> str:
        return """You are a Risk Management Officer. Monitor volatility and suggest position sizing and leverage.

IMPORTANT: You MUST respond in Chinese (中文). All analysis, explanations, and conclusions should be written in Chinese.
Use markdown format for your response with clear headings and bullet points."""

    def _build_prompt(
        self,
        symbol: str,
        current_price: float,
        klines: List[KlineData],
        df: pd.DataFrame,
        memory_ctx: str = "",
    ) -> str:
        # Calculate ATR for volatility
        volatility = 0
        if not df.empty and len(df) > 15:
            try:
                df_atr = atr(df, period=14)
                volatility = df_atr.iloc[-1].get('atr_14', 0)
            except Exception as e:
                logger.error(f"ATR calculation failed: {e}")

        memory_section = f"\n{memory_ctx}\n" if memory_ctx else ""

        prompt = f"""
        Risk Assessment for {symbol}
        Current Price: {current_price}
        Volatility (ATR 14): {volatility:.2f}
        {memory_section}
        Task:
        1. Analyze current market volatility.
        2. Suggest appropriate leverage (Low/Medium/High).
        3. Recommend stop-loss distance based on ATR.
        4. Assess overall risk level (Low/Medium/High/Extreme).

        Output concisely in markdown.
        """
        return prompt


# Legacy support: Default to Trend Analysis
class MarketAnalysisService(TrendAgentService):
    pass

market_analysis_service = MarketAnalysisService()
