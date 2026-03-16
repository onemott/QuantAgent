"""
Coordinator Agent — Aggregates signals from all specialist agents.

Algorithm:
  1. Run TrendAgent, MeanReversionAgent, RiskAgent concurrently (asyncio.gather)
  2. Collect AgentSignals with confidence scores
  3. Risk Agent acts as a VETO: if EXTREME/HIGH RISK → override to WAIT
  4. For remaining agents: confidence-weighted majority vote
  5. Synthesize a final decision prompt → LLM produces summary narrative
  6. Return CoordinationResult with all signals + final verdict
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional

from app.agents.base_agent import AgentSignal, SignalType
from app.agents.trend_agent import TrendAgent
from app.agents.mean_reversion_agent import MeanReversionAgent
from app.agents.risk_agent import RiskAgent
from app.services.llm.base import LLMFactory

logger = logging.getLogger(__name__)

# Signals considered "bullish" for vote aggregation
BULLISH_SIGNALS = {SignalType.BUY, SignalType.LONG_REVERSAL}
# Signals considered "bearish"
BEARISH_SIGNALS = {SignalType.SELL, SignalType.SHORT_REVERSAL}


@dataclass
class CoordinationResult:
    """Final output of the CoordinatorAgent."""
    symbol:          str
    final_signal:    SignalType
    confidence:      float
    summary:         str          # LLM-generated synthesis narrative
    agent_signals:   List[Dict[str, Any]] = field(default_factory=list)
    vote_breakdown:  Dict[str, float] = field(default_factory=dict)
    risk_veto:       bool = False
    timestamp:       datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol":        self.symbol,
            "final_signal":  self.final_signal.value,
            "confidence":    round(self.confidence, 3),
            "summary":       self.summary,
            "agent_signals": self.agent_signals,
            "vote_breakdown": self.vote_breakdown,
            "risk_veto":     self.risk_veto,
            "timestamp":     self.timestamp.isoformat(),
        }


class CoordinatorAgent:
    """
    Orchestrates all specialist agents and produces a unified trading decision.
    """

    def __init__(self, provider_name: Optional[str] = None):
        self.trend_agent    = TrendAgent(provider_name)
        self.mr_agent       = MeanReversionAgent(provider_name)
        self.risk_agent     = RiskAgent(provider_name)
        self.llm            = LLMFactory.create_provider(provider_name)

    # ── Main coordination entry point ─────────────────────────────────────────

    async def coordinate(
        self,
        symbol: str,
        interval: str = "1h",
    ) -> CoordinationResult:
        """
        Run all agents concurrently, aggregate their signals, and produce
        a final trading decision with narrative summary.
        """
        # Step 1: Run all agents in parallel
        trend_sig, mr_sig, risk_sig = await asyncio.gather(
            self.trend_agent.run(symbol, interval),
            self.mr_agent.run(symbol, interval),
            self.risk_agent.run(symbol, interval),
            return_exceptions=True,
        )

        # Handle exceptions from individual agents gracefully
        signals: List[AgentSignal] = []
        risk_veto = False

        for sig in [trend_sig, mr_sig, risk_sig]:
            if isinstance(sig, Exception):
                logger.warning(f"[coordinator] Agent failed: {sig}")
            else:
                signals.append(sig)

        if not signals:
            return CoordinationResult(
                symbol=symbol,
                final_signal=SignalType.WAIT,
                confidence=0.0,
                summary="所有 Agent 均发生错误，无法生成分析",
            )

        # Step 2: Risk veto check
        risk_signal = next((s for s in signals if s.agent_id == "risk"), None)
        if risk_signal and risk_signal.signal == SignalType.WAIT and risk_signal.confidence >= 0.75:
            risk_veto = True
            logger.info(f"[coordinator] Risk veto triggered (confidence={risk_signal.confidence})")

        # Step 3: Confidence-weighted vote (excluding risk agent from vote)
        trade_signals = [s for s in signals if s.agent_id != "risk"]
        bullish_weight = sum(
            s.confidence for s in trade_signals if s.signal in BULLISH_SIGNALS
        )
        bearish_weight = sum(
            s.confidence for s in trade_signals if s.signal in BEARISH_SIGNALS
        )
        neutral_weight = sum(
            s.confidence for s in trade_signals if s.signal not in BULLISH_SIGNALS | BEARISH_SIGNALS
        )
        total_weight = bullish_weight + bearish_weight + neutral_weight or 1.0

        vote_breakdown = {
            "bullish": round(bullish_weight / total_weight, 3),
            "bearish": round(bearish_weight / total_weight, 3),
            "neutral": round(neutral_weight / total_weight, 3),
        }

        # Determine raw signal before veto
        if bullish_weight > bearish_weight and bullish_weight > neutral_weight:
            raw_signal    = SignalType.BUY
            raw_confidence = bullish_weight / total_weight
        elif bearish_weight > bullish_weight and bearish_weight > neutral_weight:
            raw_signal    = SignalType.SELL
            raw_confidence = bearish_weight / total_weight
        else:
            raw_signal    = SignalType.WAIT
            raw_confidence = 0.5

        # Apply risk veto
        if risk_veto:
            final_signal    = SignalType.WAIT
            final_confidence = max(raw_confidence * 0.5, 0.3)
        else:
            final_signal    = raw_signal
            final_confidence = raw_confidence

        # Step 4: Synthesize narrative via LLM
        summary = await self._synthesize_summary(signals, final_signal, vote_breakdown, symbol)

        return CoordinationResult(
            symbol=symbol,
            final_signal=final_signal,
            confidence=round(final_confidence, 3),
            summary=summary,
            agent_signals=[s.to_dict() for s in signals],
            vote_breakdown=vote_breakdown,
            risk_veto=risk_veto,
        )

    async def coordinate_stream(
        self,
        symbol: str,
        interval: str = "1h",
    ) -> AsyncGenerator[str, None]:
        """
        Stream the coordination process step-by-step.
        Yields SSE-compatible chunks with agent progress and final decision.
        """
        yield f"[COORDINATOR] 开始多 Agent 协作分析 {symbol}...\n\n"

        # Run agents sequentially for streaming (each yields incremental progress)
        agent_results: List[AgentSignal] = []
        for agent in [self.trend_agent, self.mr_agent, self.risk_agent]:
            yield f"\n---\n### {agent.agent_name} 正在分析...\n"
            accumulated = ""
            async for chunk in agent.run_stream(symbol, interval):
                accumulated += chunk
                yield chunk
            # After each agent finishes, parse its signal
            sig_type, conf = agent.parse_signal(accumulated)
            agent_results.append(AgentSignal(
                agent_id=agent.agent_id,
                agent_name=agent.agent_name,
                symbol=symbol,
                signal=sig_type,
                confidence=conf,
                reasoning=accumulated,
            ))
            yield f"\n**{agent.agent_name} 信号: {sig_type.value} (置信度: {conf:.0%})**\n"

        # Final synthesis
        yield "\n---\n## 协调者综合决策\n"
        risk_veto = any(
            s.agent_id == "risk" and s.signal == SignalType.WAIT and s.confidence >= 0.75
            for s in agent_results
        )
        if risk_veto:
            yield "⚠️ **风险管理 Agent 触发熔断 — 建议观望**\n"

        bullish_w = sum(s.confidence for s in agent_results if s.signal in BULLISH_SIGNALS)
        bearish_w = sum(s.confidence for s in agent_results if s.signal in BEARISH_SIGNALS)
        final_sig = SignalType.BUY if (not risk_veto and bullish_w > bearish_w) else (
                    SignalType.SELL if (not risk_veto and bearish_w > bullish_w) else SignalType.WAIT)

        yield f"\n**最终信号: {final_sig.value}**\n"

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _synthesize_summary(
        self,
        signals: List[AgentSignal],
        final_signal: SignalType,
        vote_breakdown: Dict[str, float],
        symbol: str,
    ) -> str:
        """Ask LLM to write a concise synthesis of all agent outputs."""
        if not self.llm:
            return self._fallback_summary(signals, final_signal, vote_breakdown)

        agent_summaries = "\n\n".join(
            f"**{s.agent_name}** (信号: {s.signal.value}, 置信度: {s.confidence:.0%}):\n{s.reasoning[:300]}"
            for s in signals
        )
        prompt = f"""
以下是对 {symbol} 的多 Agent 协作分析结果：

{agent_summaries}

投票结果：
- 看多权重: {vote_breakdown.get('bullish', 0):.1%}
- 看空权重: {vote_breakdown.get('bearish', 0):.1%}
- 中性权重: {vote_breakdown.get('neutral', 0):.1%}

最终决策: **{final_signal.value}**

请用 2-3 段话，用中文总结这次分析的关键发现和最终决策逻辑。简洁专业。
"""
        try:
            result = await self.llm.generate(
                prompt,
                system_prompt="You are a quantitative trading coordinator. Summarize agent analysis in Chinese.",
                temperature=0.5,
            )
            # Remove <think>...</think> blocks from reasoning models
            result = re.sub(r'<think>.*?</think>', '', result, flags=re.DOTALL)
            result = re.sub(r'<think>.*$', '', result, flags=re.DOTALL)
            return result.strip()
        except Exception as e:
            logger.warning(f"[coordinator] Summary LLM failed: {e}")
            return self._fallback_summary(signals, final_signal, vote_breakdown)

    @staticmethod
    def _fallback_summary(
        signals: List[AgentSignal],
        final_signal: SignalType,
        vote_breakdown: Dict[str, float],
    ) -> str:
        lines = [f"最终信号: **{final_signal.value}**"]
        for s in signals:
            lines.append(f"- {s.agent_name}: {s.signal.value} (置信度 {s.confidence:.0%})")
        lines.append(
            f"投票: 看多 {vote_breakdown.get('bullish',0):.0%} | "
            f"看空 {vote_breakdown.get('bearish',0):.0%} | "
            f"中性 {vote_breakdown.get('neutral',0):.0%}"
        )
        return "\n".join(lines)
