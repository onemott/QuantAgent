"""
Base Agent — Foundation class for all QuantAgent AI agents.

Each agent follows a ReAct loop:
  1. observe()  — fetch market data and build context
  2. think()    — call LLM with context + memory
  3. act()      — parse LLM output into AgentSignal

Agents maintain short-term memory via Redis (5 recent analyses per symbol)
and persist summaries to PostgreSQL agent_memories table.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import pandas as pd

from app.services.llm.base import LLMFactory
from app.services.database import redis_get, redis_set, redis_delete, get_db
from app.services.embedding_service import embedding_service
from app.models.db_models import AgentMemory
from sqlalchemy import select, func, text as sql_text, desc

logger = logging.getLogger(__name__)

MEMORY_WINDOW = 5
MEMORY_TTL    = 3600 * 6  # 6 hours
SIMILARITY_THRESHOLD = 0.3  # Cosine distance threshold (0.0=identical, 2.0=opposite)

# ── Signal types ──────────────────────────────────────────────────────────────


# ── Signal types ──────────────────────────────────────────────────────────────

class SignalType(str, Enum):
    BUY            = "BUY"
    SELL           = "SELL"
    WAIT           = "WAIT"
    LONG_REVERSAL  = "LONG_REVERSAL"
    SHORT_REVERSAL = "SHORT_REVERSAL"
    HOLD           = "HOLD"


# ── Agent state machine ───────────────────────────────────────────────────────

class AgentState(str, Enum):
    IDLE      = "idle"
    OBSERVING = "observing"
    THINKING  = "thinking"
    ACTING    = "acting"
    ERROR     = "error"


# ── Signal output ─────────────────────────────────────────────────────────────

@dataclass
class AgentSignal:
    """Structured output from an agent's analysis cycle."""
    agent_id:   str
    agent_name: str
    symbol:     str
    signal:     SignalType
    confidence: float          # 0.0 ~ 1.0
    reasoning:  str            # full LLM analysis text
    indicators: Dict[str, Any] = field(default_factory=dict)  # key metrics used
    timestamp:  datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id":   self.agent_id,
            "agent_name": self.agent_name,
            "symbol":     self.symbol,
            "signal":     self.signal.value,
            "confidence": round(self.confidence, 3),
            "reasoning":  self.reasoning,
            "indicators": self.indicators,
            "timestamp":  self.timestamp.isoformat(),
        }


# ── Base Agent ────────────────────────────────────────────────────────────────

class BaseAgent:
    """
    Abstract base class for all QuantAgent AI agents.

    Subclasses must implement:
      - agent_id   (str property)
      - agent_name (str property)
      - observe()  → Dict[str, Any]
      - build_prompt(context) → str
      - system_prompt (str property)
      - parse_signal(text) → (SignalType, float)
    """

    def __init__(self, provider_name: Optional[str] = None):
        self.llm   = LLMFactory.create_provider(provider_name)
        self.state = AgentState.IDLE
        logger.info(f"[{self.agent_id}] Initialized with provider: {provider_name}")

    # ── Public API ────────────────────────────────────────────────────────────

    async def run(self, symbol: str, interval: str = "1h") -> AgentSignal:
        """
        Execute a full ReAct cycle and return a structured AgentSignal.
        """
        self.state = AgentState.OBSERVING
        try:
            context = await self.observe(symbol, interval)
            # Generate embedding for current context
            context_str = self._context_to_text(context)
            context_embedding = await embedding_service.get_embedding(context_str)
        except Exception as e:
            self.state = AgentState.ERROR
            logger.error(f"[{self.agent_id}] observe() failed: {e}")
            return self._error_signal(symbol, str(e))

        self.state = AgentState.THINKING
        try:
            memory_ctx = await self._load_memory(symbol, context_embedding)
            prompt     = self.build_prompt(context, memory_ctx)
            analysis   = await self.llm.generate(
                prompt, system_prompt=self.system_prompt, temperature=0.7
            )
        except Exception as e:
            self.state = AgentState.ERROR
            logger.error(f"[{self.agent_id}] think() failed: {e}")
            return self._error_signal(symbol, str(e))

        self.state = AgentState.ACTING
        signal_type, confidence = self.parse_signal(analysis)
        sig = AgentSignal(
            agent_id=self.agent_id,
            agent_name=self.agent_name,
            symbol=symbol,
            signal=signal_type,
            confidence=confidence,
            reasoning=analysis,
            indicators=context.get("indicators", {}),
        )

        await self._save_memory(symbol, analysis[:400], signal_type.value, confidence, context_embedding, context.get("price"))
        self.state = AgentState.IDLE
        return sig

    async def run_stream(
        self, symbol: str, interval: str = "1h"
    ) -> AsyncGenerator[str, None]:
        """
        Stream analysis output token by token.
        Saves memory after stream completes.
        """
        self.state = AgentState.OBSERVING
        context_embedding = []
        price = None
        try:
            context    = await self.observe(symbol, interval)
            price      = context.get("price")
            context_str = self._context_to_text(context)
            context_embedding = await embedding_service.get_embedding(context_str)
            
            memory_ctx = await self._load_memory(symbol, context_embedding)
            prompt     = self.build_prompt(context, memory_ctx)
        except Exception as e:
            self.state = AgentState.ERROR
            yield f"Error: {e}"
            return

        self.state = AgentState.THINKING
        accumulated = ""
        try:
            async for chunk in self.llm.stream(
                prompt, system_prompt=self.system_prompt, temperature=0.7
            ):
                accumulated += chunk
                yield chunk
        except Exception as e:
            self.state = AgentState.ERROR
            yield f"\n\nError during streaming: {e}"
            return

        # Save memory after stream finishes
        self.state = AgentState.ACTING
        signal_type, confidence = self.parse_signal(accumulated)
        await self._save_memory(symbol, accumulated[:400], signal_type.value, confidence, context_embedding, price)
        self.state = AgentState.IDLE

    # ── Abstract interface (subclasses must implement) ────────────────────────

    @property
    def agent_id(self) -> str:
        raise NotImplementedError

    @property
    def agent_name(self) -> str:
        raise NotImplementedError

    @property
    def system_prompt(self) -> str:
        raise NotImplementedError

    async def observe(self, symbol: str, interval: str) -> Dict[str, Any]:
        """Fetch market data and return context dict."""
        raise NotImplementedError

    def build_prompt(self, context: Dict[str, Any], memory_ctx: str = "") -> str:
        """Build the LLM prompt from observation context + memory."""
        raise NotImplementedError

    def parse_signal(self, text: str) -> Tuple[SignalType, float]:
        """
        Extract trading signal and confidence from LLM output text.
        Default implementation: keyword matching.
        """
        text_upper = text.upper()
        signal_map = {
            "LONG_REVERSAL":  SignalType.LONG_REVERSAL,
            "SHORT_REVERSAL": SignalType.SHORT_REVERSAL,
            "BUY":            SignalType.BUY,
            "SELL":           SignalType.SELL,
            "HOLD":           SignalType.HOLD,
            "WAIT":           SignalType.WAIT,
        }
        for keyword, sig in signal_map.items():
            if keyword in text_upper:
                # Rough confidence: based on how strong the language is
                confidence = self._estimate_confidence(text, keyword)
                return sig, confidence
        return SignalType.WAIT, 0.5

    # ── Memory layer ──────────────────────────────────────────────────────────

    async def _load_memory(self, symbol: str, current_embedding: List[float] = None) -> str:
        """
        Load recent analysis history AND similar historical cases (RAG).
        """
        rag_context = ""
        recent_context = ""

        # 1. RAG Search (Long-term Memory)
        if current_embedding and len(current_embedding) > 0:
            try:
                async with get_db() as session:
                    stmt = (
                        select(AgentMemory)
                        .where(AgentMemory.agent_type == self.agent_id)
                        .where(AgentMemory.symbol == symbol)
                        .where(AgentMemory.market_state_embedding.isnot(None))
                        .order_by(AgentMemory.market_state_embedding.cosine_distance(current_embedding))
                        .limit(3)
                    )
                    result = await session.execute(stmt)
                    rows = result.scalars().all()
                    
                    rag_memories = []
                    for row in rows:
                        pnl_str = f" | 盈亏: {row.outcome_pnl:.2f}%" if row.outcome_pnl is not None else ""
                        date_str = row.created_at.strftime('%Y-%m-%d')
                        rag_memories.append(
                            f"- [相似历史 {date_str}] {row.summary[:100]}... "
                            f"(信号: {row.signal}, 置信度: {row.confidence:.0%}{pnl_str})"
                        )
                    
                    if rag_memories:
                        rag_context = "\n".join(["[History Lesson: 基于相似行情的历史回顾]", *rag_memories])
                        
            except Exception as e:
                logger.warning(f"[{self.agent_id}] RAG search failed: {e}")

        # 2. Recent History (Short-term Memory)
        redis_key = f"agent_memory:{self.agent_id}:{symbol}"
        cached = await redis_get(redis_key)
        memories = cached if cached else []

        if not memories:
            try:
                async with get_db() as session:
                    stmt = (
                        select(AgentMemory)
                        .where(AgentMemory.agent_type == self.agent_id)
                        .where(AgentMemory.symbol == symbol)
                        .order_by(desc(AgentMemory.created_at))
                        .limit(MEMORY_WINDOW)
                    )
                    result = await session.execute(stmt)
                    rows = result.scalars().all()
                    memories = [
                        {
                            "summary":    row.summary[:200],
                            "signal":     row.signal,
                            "confidence": row.confidence,
                            "time":       row.created_at.strftime("%Y-%m-%d %H:%M") if row.created_at else "",
                        }
                        for row in reversed(rows) # Chronological order
                    ]
                    await redis_set(redis_key, memories, ttl=MEMORY_TTL)
            except Exception as e:
                logger.warning(f"[{self.agent_id}] Memory load failed: {e}")

        if memories:
            lines = [f"[近期历史分析（最近 {len(memories)} 条）]"]
            for m in memories:
                sig_str  = f" | 信号: {m['signal']}" if m.get("signal") else ""
                conf_str = f" | 置信度: {m['confidence']:.0%}" if m.get("confidence") else ""
                lines.append(f"- [{m.get('time','')}]{sig_str}{conf_str}: {m.get('summary','')}")
            recent_context = "\n".join(lines)

        # Combine
        full_context = []
        if rag_context:
            full_context.append(rag_context)
        if recent_context:
            full_context.append(recent_context)
            
        return "\n\n".join(full_context)

    async def _save_memory(
        self,
        symbol: str,
        summary: str,
        signal: Optional[str] = None,
        confidence: Optional[float] = None,
        embedding: List[float] = None,
        price: Optional[float] = None,
    ) -> None:
        """Persist analysis summary to PostgreSQL and clear Redis cache."""
        try:
            async with get_db() as session:
                entry = AgentMemory(
                    agent_type=self.agent_id,
                    symbol=symbol,
                    summary=summary[:500],
                    signal=signal,
                    confidence=confidence,
                    market_state_embedding=embedding,
                    entry_price=price
                )
                session.add(entry)
            await redis_delete(f"agent_memory:{self.agent_id}:{symbol}")
        except Exception as e:
            logger.warning(f"[{self.agent_id}] Memory save failed: {e}")

    def _context_to_text(self, context: Dict[str, Any]) -> str:
        """
        Convert context dict to a string suitable for embedding.
        Focuses on price and indicators.
        """
        try:
            # Create a compact representation
            parts = [f"Symbol: {context.get('symbol')}"]
            parts.append(f"Price: {context.get('price')}")
            
            indicators = context.get("indicators", {})
            for k, v in indicators.items():
                parts.append(f"{k}: {v}")
                
            return ", ".join(parts)
        except Exception:
            return str(context)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _error_signal(self, symbol: str, error: str) -> AgentSignal:
        return AgentSignal(
            agent_id=self.agent_id,
            agent_name=self.agent_name,
            symbol=symbol,
            signal=SignalType.WAIT,
            confidence=0.0,
            reasoning=f"Error: {error}",
        )

    def _estimate_confidence(self, text: str, keyword: str) -> float:
        """
        Heuristic confidence scoring based on text strength indicators.
        Returns a value in [0.4, 0.95].
        """
        text_lower = text.lower()
        confidence = 0.6  # baseline

        strong_words  = ["strong", "clear", "definitive", "明显", "强", "确定", "明确"]
        weak_words    = ["possible", "may", "might", "uncertain", "可能", "或许", "不确定"]
        caution_words = ["caution", "risk", "warning", "注意", "谨慎", "警告"]

        for w in strong_words:
            if w in text_lower:
                confidence += 0.1
                break
        for w in weak_words:
            if w in text_lower:
                confidence -= 0.1
                break
        for w in caution_words:
            if w in text_lower:
                confidence -= 0.05
                break

        return round(max(0.4, min(0.95, confidence)), 2)
