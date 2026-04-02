"""
Market Data Endpoints
"""
import asyncio
from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import StreamingResponse
from typing import List, Optional, AsyncGenerator, Dict, Any
from datetime import datetime
from pydantic import BaseModel
import json
import re
import logging

from app.services.binance_service import binance_service
from app.services.coingecko_service import coingecko_service
from app.models.market_data import KlineResponse, TickerData, MarketOverview, PriceComparison

router = APIRouter()
logger = logging.getLogger(__name__)


def _clean_think_tags(text: str) -> str:
    """Remove <think>...</think> content from LLM output."""
    if not text:
        return text
    # Remove <think>...</think> blocks including content inside
    cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    # Also handle case where closing tag might be missing or malformed
    cleaned = re.sub(r'<think>.*$', '', cleaned, flags=re.DOTALL)
    return cleaned.strip()


@router.get("/klines/{symbol}", response_model=KlineResponse)
async def get_klines(
    symbol: str,
    interval: str = Query("1h", description="Kline interval (1m, 5m, 15m, 1h, 4h, 1d)"),
    limit: int = Query(100, ge=1, le=1000),
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None
):
    """
    从 Binance 获取 K 线/Candlestick 数据
    
    支持的时间周期: 1m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d, 3d, 1w, 1M
    """
    try:
        # 转换 symbol 格式 (BTCUSDT -> BTC/USDT)
        formatted_symbol = f"{symbol[:-4]}/{symbol[-4:]}" if len(symbol) > 4 else symbol
        
        # 转换时间戳
        since = None
        if start_time:
            since = int(start_time.timestamp() * 1000)
        
        klines = await binance_service.get_klines(
            symbol=formatted_symbol,
            timeframe=interval,
            limit=limit,
            since=since
        )
        
        return KlineResponse(
            symbol=symbol,
            interval=interval,
            data=klines,
            source="binance"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch klines: {str(e)}")


@router.get("/ticker/{symbol}", response_model=TickerData)
async def get_ticker(symbol: str):
    """
    从 Binance 获取 24hr ticker 数据
    """
    try:
        # 转换 symbol 格式
        formatted_symbol = f"{symbol[:-4]}/{symbol[-4:]}" if len(symbol) > 4 else symbol
        
        ticker = await binance_service.get_ticker(formatted_symbol)
        return ticker
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch ticker: {str(e)}")


@router.get("/symbols")
async def get_symbols():
    """
    获取所有可用的交易对
    """
    try:
        symbols = await binance_service.get_symbols()
        return {
            "symbols": [
                {"symbol": s.symbol, "base": s.base, "quote": s.quote}
                for s in symbols[:100]  # 限制返回数量
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch symbols: {str(e)}")


@router.get("/price/{symbol}")
async def get_price(symbol: str):
    """
    获取指定交易对的当前价格（从 Binance）
    """
    try:
        formatted_symbol = f"{symbol[:-4]}/{symbol[-4:]}" if len(symbol) > 4 else symbol
        price = await binance_service.get_price(formatted_symbol)
        return {"symbol": symbol, "price": price, "source": "binance"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch price: {str(e)}")


@router.get("/orderbook/{symbol}")
async def get_order_book(symbol: str, limit: int = Query(100, ge=1, le=500)):
    """
    获取订单簿数据（从 Binance）
    """
    try:
        formatted_symbol = f"{symbol[:-4]}/{symbol[-4:]}" if len(symbol) > 4 else symbol
        order_book = await binance_service.get_order_book(formatted_symbol, limit)
        return order_book
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch order book: {str(e)}")


# ============== CoinGecko Endpoints ==============

@router.get("/coingecko/overview", response_model=List[MarketOverview])
async def get_coingecko_overview(
    vs_currency: str = Query("usd", description="计价货币"),
    per_page: int = Query(100, ge=1, le=250),
    page: int = Query(1, ge=1)
):
    """
    从 CoinGecko 获取市场概览数据（市值排名、价格、涨跌幅等）
    """
    try:
        markets = coingecko_service.get_market_overview(
            vs_currency=vs_currency,
            per_page=per_page,
            page=page
        )
        return markets
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch market overview: {str(e)}")


@router.get("/coingecko/price/{coin_id}")
async def get_coingecko_price(
    coin_id: str,
    vs_currency: str = Query("usd", description="计价货币")
):
    """
    从 CoinGecko 获取指定币种价格
    
    coin_id: 如 bitcoin, ethereum, solana
    """
    try:
        price = coingecko_service.get_price(coin_id, vs_currency)
        return {"coin_id": coin_id, "price": price, "currency": vs_currency}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch price: {str(e)}")


@router.get("/coingecko/trending")
async def get_trending_coins():
    """
    获取 CoinGecko Trending（热门）币种
    """
    try:
        trending = coingecko_service.get_trending_coins()
        return {"trending": trending}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch trending coins: {str(e)}")


@router.get("/coingecko/search")
async def search_coins(query: str = Query(..., description="搜索关键词")):
    """
    搜索币种
    """
    try:
        results = coingecko_service.search_coins(query)
        return {"results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to search coins: {str(e)}")


# ============== Price Comparison ==============

@router.get("/compare/{symbol}", response_model=PriceComparison)
async def compare_prices(symbol: str):
    """
    对比 Binance 和 CoinGecko 的价格
    
    symbol: 如 BTC, ETH, SOL
    """
    try:
        # 获取 Binance 价格
        formatted_symbol = f"{symbol}/USDT"
        try:
            binance_price = await binance_service.get_price(formatted_symbol)
        except Exception:
            binance_price = None
        
        # 使用 CoinGecko 服务对比价格
        comparison = coingecko_service.compare_price(symbol, binance_price)
        return comparison
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to compare prices: {str(e)}")


# ============== Coordinator ==============

@router.get("/coordinate/{symbol}")
async def coordinate_agents(
    symbol: str,
    interval: str = "1h",
    provider: Optional[str] = Query(None, description="LLM Provider (ollama, openai, openrouter)")
):
    """
    协调者端点：聚合所有 Agent 信号并生成综合决策
    """
    from app.agents.coordinator_agent import CoordinatorAgent
    
    try:
        coordinator = CoordinatorAgent(provider_name=provider)
        formatted_symbol = f"{symbol[:-4]}/{symbol[-4:]}" if len(symbol) > 4 else symbol
        result = await coordinator.coordinate(formatted_symbol, interval)
        return result.to_dict()
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Coordination failed: {str(e)}")


# ============== Lightweight Coordinator (Frontend Results) ==============

class AgentSignalInput(BaseModel):
    agent_id: str
    agent_name: str
    signal: str
    confidence: float
    reasoning: str


class CoordinateRequest(BaseModel):
    symbol: str
    interval: str = "1h"
    agent_signals: List[AgentSignalInput]
    provider: Optional[str] = None


@router.post("/coordinate/aggregate")
async def coordinate_aggregate(req: CoordinateRequest):
    """
    轻量协调者端点：接收前端已收集的 Agent 结果，直接进行综合决策。
    避免重复运行所有 Agent，提高响应速度。
    """
    from app.agents.coordinator_agent import CoordinatorAgent, SignalType, BULLISH_SIGNALS, BEARISH_SIGNALS
    from app.services.llm.base import LLMFactory
    
    try:
        # Convert input signals to format expected by coordinator logic
        signals_data = []
        for s in req.agent_signals:
            signals_data.append({
                "agent_id": s.agent_id,
                "agent_name": s.agent_name,
                "signal": s.signal,
                "confidence": s.confidence,
                "reasoning": s.reasoning,
            })
        
        # Risk veto check
        risk_signal = next((s for s in req.agent_signals if s.agent_id == "risk"), None)
        risk_veto = False
        if risk_signal and risk_signal.signal == "WAIT" and risk_signal.confidence >= 0.75:
            risk_veto = True
        
        # Confidence-weighted vote (excluding risk agent from vote)
        trade_signals = [s for s in req.agent_signals if s.agent_id != "risk"]
        bullish_weight = sum(s.confidence for s in trade_signals if s.signal in ["BUY", "LONG_REVERSAL"])
        bearish_weight = sum(s.confidence for s in trade_signals if s.signal in ["SELL", "SHORT_REVERSAL"])
        neutral_weight = sum(s.confidence for s in trade_signals if s.signal not in ["BUY", "LONG_REVERSAL", "SELL", "SHORT_REVERSAL"])
        total_weight = bullish_weight + bearish_weight + neutral_weight or 1.0
        
        vote_breakdown = {
            "bullish": round(bullish_weight / total_weight, 3),
            "bearish": round(bearish_weight / total_weight, 3),
            "neutral": round(neutral_weight / total_weight, 3),
        }
        
        # Determine raw signal before veto
        if bullish_weight > bearish_weight and bullish_weight > neutral_weight:
            raw_signal = "BUY"
            raw_confidence = bullish_weight / total_weight
        elif bearish_weight > bullish_weight and bearish_weight > neutral_weight:
            raw_signal = "SELL"
            raw_confidence = bearish_weight / total_weight
        else:
            raw_signal = "WAIT"
            raw_confidence = 0.5
        
        # Apply risk veto
        if risk_veto:
            final_signal = "WAIT"
            final_confidence = max(raw_confidence * 0.5, 0.3)
        else:
            final_signal = raw_signal
            final_confidence = raw_confidence
        
        # Generate summary via LLM
        llm = LLMFactory.create_provider(req.provider)
        agent_summaries = "\n\n".join(
            f"**{s.agent_name}** (信号: {s.signal}, 置信度: {s.confidence:.0%}):\n{s.reasoning[:300]}"
            for s in req.agent_signals
        )
        
        prompt = f"""以下是对 {req.symbol} 的多 Agent 协作分析结果：

{agent_summaries}

投票结果：
- 看多权重: {vote_breakdown.get('bullish', 0):.1%}
- 看空权重: {vote_breakdown.get('bearish', 0):.1%}
- 中性权重: {vote_breakdown.get('neutral', 0):.1%}

最终决策: **{final_signal}**

请用 2-3 段话，用中文总结这次分析的关键发现和最终决策逻辑。简洁专业。"""
        
        try:
            summary = await llm.generate(
                prompt,
                system_prompt="You are a quantitative trading coordinator. Summarize agent analysis in Chinese.",
                temperature=0.5,
            )
            # Clean think tags from summary
            summary = _clean_think_tags(summary)
        except Exception as e:
            logger.warning(f"[coordinator] Summary LLM failed: {e}")
            summary = f"最终信号: **{final_signal}** (置信度: {final_confidence:.0%})"
        
        return {
            "symbol": req.symbol,
            "final_signal": final_signal,
            "confidence": round(final_confidence, 3),
            "summary": summary,
            "agent_signals": signals_data,
            "vote_breakdown": vote_breakdown,
            "risk_veto": risk_veto,
            "timestamp": datetime.utcnow().isoformat(),
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Coordination failed: {str(e)}")


# ============== AI Analysis ==============

@router.get("/agent-analysis/{agent_type}/{symbol}")
async def analyze_market_v2(
    agent_type: str,
    symbol: str, 
    interval: str = "1h",
    provider: Optional[str] = Query(None, description="LLM Provider (openai, ollama, openrouter)")
):
    """
    Use specialized AI Agents to analyze market data
    """
    from app.services.market_analysis_service import (
        TrendAgentService, 
        MeanReversionAgentService, 
        RiskAgentService
    )
    
    try:
        # Map agent_type to service class
        agent_map = {
            "trend": TrendAgentService,
            "mean_reversion": MeanReversionAgentService,
            "risk": RiskAgentService
        }
        
        service_class = agent_map.get(agent_type.lower())
        if not service_class:
            raise HTTPException(status_code=400, detail=f"Invalid agent type: {agent_type}")
            
        # Create service instance
        service = service_class(provider_name=provider)
        
        # Format symbol
        formatted_symbol = f"{symbol[:-4]}/{symbol[-4:]}" if len(symbol) > 4 else symbol
        
        analysis = await service.analyze(formatted_symbol, interval)
        return {
            "symbol": symbol, 
            "agent_type": agent_type,
            "analysis": analysis, 
            "provider": provider or "default"
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"AI analysis failed: {str(e)}")


@router.get("/analysis/{symbol}")
async def analyze_market(
    symbol: str, 
    interval: str = "1h",
    provider: Optional[str] = Query(None, description="LLM Provider (openai, ollama)")
):
    """
    Legacy endpoint for market analysis
    """
    from app.services.market_analysis_service import MarketAnalysisService
    
    try:
        service = MarketAnalysisService(provider_name=provider)
        formatted_symbol = f"{symbol[:-4]}/{symbol[-4:]}" if len(symbol) > 4 else symbol
        analysis = await service.analyze_market(formatted_symbol, interval)
        return {"symbol": symbol, "analysis": analysis, "provider": provider or "default"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI analysis failed: {str(e)}")


@router.get("/agent-analysis-stream/{agent_type}/{symbol}")
async def analyze_market_stream(
    agent_type: str,
    symbol: str,
    interval: str = "1h",
    provider: Optional[str] = Query(None, description="LLM Provider (ollama, openai, openrouter)")
):
    """
    流式 SSE 端点：使用 AI Agent 分析市场数据，逐 chunk 推送输出。
    主要用于 Ollama 本地模型，支持思考链（<think>...</think>）实时展示。
    """
    from app.services.market_analysis_service import (
        TrendAgentService,
        MeanReversionAgentService,
        RiskAgentService
    )

    agent_map = {
        "trend": TrendAgentService,
        "mean_reversion": MeanReversionAgentService,
        "risk": RiskAgentService
    }

    service_class = agent_map.get(agent_type.lower())
    if not service_class:
        raise HTTPException(status_code=400, detail=f"Invalid agent type: {agent_type}")

    formatted_symbol = f"{symbol[:-4]}/{symbol[-4:]}" if len(symbol) > 4 else symbol
    service = service_class(provider_name=provider)

    async def event_generator() -> AsyncGenerator[str, None]:
        accumulated = ""
        try:
            async for chunk in service.analyze_stream(formatted_symbol, interval):
                accumulated += chunk
                payload = json.dumps({"chunk": chunk}, ensure_ascii=False)
                yield f"data: {payload}\n\n"
        except Exception as e:
            error_payload = json.dumps({"error": str(e)}, ensure_ascii=False)
            yield f"data: {error_payload}\n\n"
        finally:
            # Extract signal and confidence from accumulated analysis
            signal = service._extract_signal(accumulated) if accumulated else None
            confidence = 0.8 if signal else 0.6
            done_payload = json.dumps({
                "done": True,
                "signal": signal,
                "confidence": confidence
            }, ensure_ascii=False)
            yield f"data: {done_payload}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


@router.get("/ollama/status")
async def check_ollama_status():
    """
    检查 Ollama 本地服务是否可用
    """
    import aiohttp
    from app.core.config import settings
    
    ollama_url = settings.OLLAMA_BASE_URL
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{ollama_url}/api/tags", timeout=aiohttp.ClientTimeout(total=3)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    models = [m.get("name", "") for m in data.get("models", [])]
                    return {
                        "online": True,
                        "url": ollama_url,
                        "models": models,
                        "configured_model": settings.OLLAMA_MODEL,
                        "model_available": settings.OLLAMA_MODEL in models
                    }
                else:
                    return {"online": False, "url": ollama_url, "error": f"HTTP {resp.status}"}
    except Exception as e:
        return {
            "online": False,
            "url": ollama_url,
            "error": str(e),
            "hint": f"请先安装并启动 Ollama: https://ollama.com/download，然后运行 'ollama run {settings.OLLAMA_MODEL}'"
        }


# ── Manual Backfill ─────────────────────────────────────────────────────────────

class BackfillRequest(BaseModel):
    symbol: Optional[str] = None   # e.g. BTCUSDT, defaults to all
    interval: Optional[str] = None  # e.g. 1m, 1h, defaults to all
    mode: str = "sync"              # "full" or "sync"


@router.post("/backfill", status_code=202)
async def trigger_backfill(req: BackfillRequest):
    """
    手动触发历史数据补数任务。

    - **symbol**: 币种 (BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, DOGEUSDT)，默认全部
    - **interval**: 周期 (1m, 5m, 15m, 1h, 4h, 1d)，默认全部
    - **mode**: "full" (全量回填) 或 "sync" (增量同步)，默认 sync
    """
    from app.core.config import settings
    from app.services.clickhouse_service import clickhouse_service

    VALID_INTERVALS = ["1m", "5m", "15m", "1h", "4h", "1d"]
    VALID_SYMBOLS = list(settings.SYMBOLS)

    symbols = [req.symbol] if req.symbol else VALID_SYMBOLS
    intervals = [req.interval] if req.interval else VALID_INTERVALS

    # Validate
    symbols = [s for s in symbols if s in VALID_SYMBOLS]
    intervals = [i for i in intervals if i in VALID_INTERVALS]
    mode = req.mode if req.mode in ("full", "sync") else "sync"

    if not symbols:
        raise HTTPException(status_code=400, detail=f"Invalid symbol. Valid: {VALID_SYMBOLS}")
    if not intervals:
        raise HTTPException(status_code=400, detail=f"Invalid interval. Valid: {VALID_INTERVALS}")

    # Run backfill as a fire-and-forget background task
    asyncio.create_task(_run_backfill(symbols, intervals, mode))

    return {
        "status": "started",
        "message": f"补数任务已启动: {symbols} x {intervals}, mode={mode}",
        "symbols": symbols,
        "intervals": intervals,
        "mode": mode,
    }


async def _run_backfill(symbols: List[str], intervals: List[str], mode: str):
    """
    Background backfill implementation. Writes to ClickHouse for each symbol/interval.
    """
    import asyncio
    from datetime import datetime, timezone, timedelta
    from app.services.binance_service import binance_service
    from app.services.clickhouse_service import clickhouse_service

    INTERVALS_CFG = {
        "1m":  {"days_back": 7,   "ms_delta": 60_000},
        "5m":  {"days_back": 30,  "ms_delta": 300_000},
        "15m": {"days_back": 60,  "ms_delta": 900_000},
        "1h":  {"days_back": 365, "ms_delta": 3_600_000},
        "4h":  {"days_back": 730, "ms_delta": 14_400_000},
        "1d":  {"days_back": 1825, "ms_delta": 86_400_000},
    }

    def to_binance(sym: str) -> str:
        if '/' in sym:
            return sym
        if sym.endswith('USDT'):
            return f"{sym[:-4]}/USDT"
        return sym

    now = datetime.now(timezone.utc)
    total = 0

    for symbol in symbols:
        for interval in intervals:
            config = INTERVALS_CFG.get(interval, {})
            if mode == "full":
                start_dt = now - timedelta(days=config.get("days_back", 7))
                start_ms = int(start_dt.timestamp() * 1000)
            else:
                max_ts = await clickhouse_service.get_max_timestamp(symbol, interval)
                if max_ts is None:
                    start_dt = now - timedelta(days=config.get("days_back", 7))
                    start_ms = int(start_dt.timestamp() * 1000)
                else:
                    start_ms = int(max_ts.timestamp() * 1000) - config.get("ms_delta", 60000)

            end_ms = int(now.timestamp() * 1000)
            current_ms = start_ms
            count = 0

            while current_ms < end_ms:
                try:
                    klines = await binance_service.get_klines(
                        symbol=to_binance(symbol),
                        timeframe=interval,
                        limit=1000,
                        since=current_ms,
                    )
                    if not klines:
                        break
                    rows = [
                        {
                            "open_time":  k.timestamp,
                            "open":       k.open,
                            "high":       k.high,
                            "low":        k.low,
                            "close":      k.close,
                            "volume":     k.volume,
                            "close_time": k.close_time,
                        }
                        for k in klines
                    ]
                    await clickhouse_service.insert_klines(symbol, interval, rows)
                    count += len(klines)
                    last_ts = klines[-1].timestamp.timestamp() * 1000
                    current_ms = int(last_ts + config.get("ms_delta", 60000))
                    await asyncio.sleep(0.3)
                except Exception as e:
                    logger.warning(f"[backfill] {symbol}/{interval} batch failed: {e}")
                    break

            logger.info(f"[backfill] {symbol}/{interval} ({mode}): wrote {count} bars")
            total += count

    logger.info(f"[backfill] All done. Total {total} bars written.")


# ── Data Range Health Check ──────────────────────────────────────────────────────

@router.get("/backfill/status")
async def backfill_status():
    """
    返回所有币种/周期的数据范围摘要（用于前端展示数据完整性状态）。
    """
    from app.services.clickhouse_service import clickhouse_service
    from app.core.config import settings

    VALID_INTERVALS = ["1m", "5m", "15m", "1h", "4h", "1d"]
    ranges = await clickhouse_service.get_all_data_ranges()

    # Build a dict keyed by symbol/interval
    data_map: Dict[str, Dict[str, Any]] = {}
    for r in ranges:
        key = f"{r['symbol']}/{r['interval']}"
        data_map[key] = r

    # Fill in missing symbol/interval combos
    for sym in settings.SYMBOLS:
        for iv in VALID_INTERVALS:
            key = f"{sym}/{iv}"
            if key not in data_map:
                data_map[key] = {
                    "symbol": sym,
                    "interval": iv,
                    "min_time": None,
                    "max_time": None,
                    "row_count": 0,
                }

    # Check staleness
    now = datetime.now(timezone.utc)
    stale_threshold = timedelta(hours=1)

    result = []
    for key, info in sorted(data_map.items()):
        max_t = info.get("max_time")
        stale = False
        if max_t is not None:
            if isinstance(max_t, datetime):
                stale = (now - max_t) > stale_threshold
            else:
                # ClickHouse may return naive datetime
                import re
                stale = False  # defer
        result.append({**info, "stale": stale})

    return {"intervals": result, "checked_at": now.isoformat()}
