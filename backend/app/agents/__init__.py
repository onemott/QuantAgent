"""
Multi-Agent Collaboration Framework for QuantAgent OS
=====================================================

Architecture:
  BaseAgent          — Base class with tool-calling, memory, state machine
  TrendAgent         — Analyzes price trends and momentum
  MeanReversionAgent — Identifies overbought/oversold reversal setups
  RiskAgent          — Assesses volatility and portfolio risk
  CoordinatorAgent   — Aggregates signals → majority vote → final decision

Each agent follows ReAct-style reasoning:
  1. Observe (fetch market data / indicators)
  2. Think (LLM analysis with memory context)
  3. Act (produce structured Signal)

CoordinatorAgent combines all three signals using confidence-weighted voting.
"""

from app.agents.base_agent import BaseAgent, AgentSignal, AgentState
from app.agents.trend_agent import TrendAgent
from app.agents.mean_reversion_agent import MeanReversionAgent
from app.agents.risk_agent import RiskAgent
from app.agents.coordinator_agent import CoordinatorAgent

__all__ = [
    "BaseAgent",
    "AgentSignal",
    "AgentState",
    "TrendAgent",
    "MeanReversionAgent",
    "RiskAgent",
    "CoordinatorAgent",
]
