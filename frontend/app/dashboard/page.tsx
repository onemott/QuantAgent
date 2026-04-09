"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import dynamic from "next/dynamic";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const TradingViewChart = dynamic(
  () => import("@/components/charts/TradingViewChart").then((mod) => mod.TradingViewChart),
  { ssr: false }
);
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  TrendingUp, TrendingDown, Activity, BarChart3, Settings,
  DollarSign, BarChart2, RefreshCw, WifiOff,
  ChevronDown, ChevronUp, Brain, Shield, Zap, X, Plus, Minus,
  Wallet, History, BarChart
} from "lucide-react";

// ─── TypeScript Interfaces ─────────────────────────────────────────────────
interface Ticker {
  symbol: string;
  price: number;
  change_24h: number;
  change_percent: number;
  volume: number;
  high_24h?: number;
  low_24h?: number;
}

interface Position {
  symbol: string;
  quantity: number;
  avg_price: number;
  mark_price: number;
  pnl: number;
  pnl_pct: number;
}

interface RiskStatus {
  kill_switch_active: boolean;
  drawdown_breached: boolean;
  total_drawdown_pct: number;
  drawdown_limit_pct: number;
  daily_loss_breached: boolean;
  daily_pnl: number;
  daily_loss_limit_pct: number;
  max_leverage: number;
}

interface ComparisonData {
  binance_price: number | null;
  coingecko_price: number | null;
  price_diff: number | null;
  price_diff_percent: number | null;
}

interface TrendingCoinItem {
  id: string;
  symbol: string;
  name: string;
  thumb: string;
  market_cap_rank: number;
  price_btc?: number;
}

interface TrendingCoin {
  item: TrendingCoinItem;
}

const COOLDOWN_SECONDS = 30;

// 动态获取 WebSocket URL，优先适配当前环境
const getWsUrl = () => {
  if (typeof window === "undefined") return "";
  
  // 统一使用相对路径并通过 Next.js 的 rewrites 转发，避免硬编码的绝对域名路径
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/market`;
};

type AnalysisCache = Record<string, { result: string; timestamp: number; outputContent?: string; thinkingContent?: string }>;
type CooldownTracker = Record<string, number>;

// 每个 Agent 对应的回测策略配置
const AGENT_STRATEGY_MAP: Record<string, { strategy_type: string; params: Record<string, number>; interval: string; limit: number }> = {
  trend:          { strategy_type: "ma",   params: { short_period: 10, long_period: 30 }, interval: "1d", limit: 200 },
  mean_reversion: { strategy_type: "boll", params: { period: 20, std_dev: 2.0 },          interval: "1d", limit: 200 },
  risk:           { strategy_type: "rsi",  params: { period: 14, oversold: 30, overbought: 70 }, interval: "1d", limit: 200 },
};

// ─── Order Panel ───────────────────────────────────────────────────────────
interface OrderPanelProps {
  symbol: string;
  currentPrice: number | null;
  onClose: () => void;
  onOrderPlaced: () => void;
}

function OrderPanel({ symbol, currentPrice, onClose, onOrderPlaced }: OrderPanelProps) {
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [quantity, setQuantity] = useState("0.01");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const estimatedCost = currentPrice ? parseFloat(quantity || "0") * currentPrice : 0;

  const handleSubmit = async () => {
    setError(null); setSuccess(null);
    const qty = parseFloat(quantity);
    if (isNaN(qty) || qty <= 0) { setError("请输入有效数量"); return; }
    setLoading(true);
    try {
      const res = await fetch("/api/v1/trading/orders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol, side, order_type: "MARKET", quantity: qty }),
      });
      const data = await res.json();
      if (!res.ok) { setError(data.detail || "下单失败"); return; }
      setSuccess(`${side} ${qty} ${symbol} @ $${data.price?.toFixed(2)} ✓`);
      onOrderPlaced();
    } catch {
      setError("网络错误，请检查后端连接");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center">
      <div className="bg-slate-900 border border-slate-700 rounded-2xl p-6 w-[360px] shadow-2xl">
        <div className="flex items-center justify-between mb-5">
          <h3 className="text-slate-100 font-bold text-lg">模拟下单</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-100 transition-colors">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Symbol */}
        <div className="mb-4 p-3 bg-slate-800 rounded-xl">
          <div className="flex items-center justify-between">
            <span className="text-slate-400 text-sm">交易对</span>
            <span className="text-slate-100 font-bold">{symbol}</span>
          </div>
          {currentPrice && (
            <div className="flex items-center justify-between mt-1">
              <span className="text-slate-500 text-xs">当前价格</span>
              <span className="text-blue-400 text-sm font-mono">${currentPrice.toLocaleString()}</span>
            </div>
          )}
        </div>

        {/* Buy / Sell Toggle */}
        <div className="flex rounded-xl overflow-hidden mb-4 border border-slate-700">
          <button
            onClick={() => setSide("BUY")}
            className={`flex-1 py-2.5 text-sm font-bold transition-all ${
              side === "BUY" ? "bg-green-600 text-white" : "bg-slate-800 text-slate-400 hover:text-slate-200"
            }`}
          >
            买入 BUY
          </button>
          <button
            onClick={() => setSide("SELL")}
            className={`flex-1 py-2.5 text-sm font-bold transition-all ${
              side === "SELL" ? "bg-red-600 text-white" : "bg-slate-800 text-slate-400 hover:text-slate-200"
            }`}
          >
            卖出 SELL
          </button>
        </div>

        {/* Quantity */}
        <div className="mb-4">
          <label className="text-slate-400 text-xs mb-1.5 block">数量</label>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setQuantity(q => Math.max(0.001, parseFloat(q) - 0.01).toFixed(4))}
              className="w-8 h-8 bg-slate-800 rounded-lg flex items-center justify-center text-slate-400 hover:text-slate-100 border border-slate-700"
            >
              <Minus className="w-3 h-3" />
            </button>
            <input
              type="number"
              value={quantity}
              onChange={e => setQuantity(e.target.value)}
              step="0.01"
              min="0.001"
              className="flex-1 bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-slate-100 text-sm text-center focus:outline-none focus:border-blue-500"
            />
            <button
              onClick={() => setQuantity(q => (parseFloat(q) + 0.01).toFixed(4))}
              className="w-8 h-8 bg-slate-800 rounded-lg flex items-center justify-center text-slate-400 hover:text-slate-100 border border-slate-700"
            >
              <Plus className="w-3 h-3" />
            </button>
          </div>
          {estimatedCost > 0 && (
            <p className="text-slate-500 text-xs mt-1.5 text-right">
              预估金额：<span className="text-slate-300">${estimatedCost.toLocaleString(undefined, { maximumFractionDigits: 2 })}</span>
            </p>
          )}
        </div>

        {/* Quick qty buttons */}
        <div className="flex gap-2 mb-4">
          {["0.01", "0.1", "0.5", "1"].map(v => (
            <button
              key={v}
              onClick={() => setQuantity(v)}
              className={`flex-1 py-1.5 text-xs rounded-lg border transition-all ${
                quantity === v
                  ? "bg-blue-600/20 border-blue-500/50 text-blue-400"
                  : "bg-slate-800 border-slate-700 text-slate-400 hover:text-slate-200"
              }`}
            >
              {v}
            </button>
          ))}
        </div>

        {error   && <div className="mb-3 p-2 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-xs">{error}</div>}
        {success && <div className="mb-3 p-2 bg-green-500/10 border border-green-500/30 rounded-lg text-green-400 text-xs">{success}</div>}

        <Button
          onClick={handleSubmit}
          disabled={loading}
          className={`w-full font-bold py-3 rounded-xl ${
            side === "BUY"
              ? "bg-green-600 hover:bg-green-500 text-white"
              : "bg-red-600 hover:bg-red-500 text-white"
          }`}
        >
          {loading ? <RefreshCw className="w-4 h-4 animate-spin mr-2" /> : null}
          {loading ? "提交中..." : `${side === "BUY" ? "买入" : "卖出"} ${symbol}`}
        </Button>
      </div>
    </div>
  );
}

// ─── Main Dashboard ─────────────────────────────────────────────────────────
export default function DashboardPage() {
  const [ticker, setTicker] = useState<Ticker | null>(null);
  const [currentSymbol, setCurrentSymbol] = useState("BTCUSDT");
  const [currentInterval, setCurrentInterval] = useState("1h");
  const [wsStatus, setWsStatus] = useState<"connecting" | "connected" | "disconnected">("connecting");

  // Paper trading state
  const [balance, setBalance] = useState<{ total_balance: number; available_balance: number } | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [riskStatus, setRiskStatus] = useState<RiskStatus | null>(null);
  const [showOrderPanel, setShowOrderPanel] = useState(false);
  const [positionsLoading, setPositionsLoading] = useState(true);

  // Ollama status
  const [ollamaStatus, setOllamaStatus] = useState<{ online: boolean; checked: boolean; model_available?: boolean }>({ online: false, checked: false });
  const [comparisonData, setComparisonData] = useState<ComparisonData | null>(null);
  const [loadingComparison, setLoadingComparison] = useState(false);
  const [trendingCoins, setTrendingCoins] = useState<TrendingCoin[]>([]);

  useEffect(() => {
    // Fetch trending coins
    fetch("/api/v1/market/coingecko/trending")
      .then(r => r.json())
      .then(d => setTrendingCoins(d.trending || []))
      .catch(() => {
        // Mock if failed
        setTrendingCoins([
          { item: { id: "bitcoin", symbol: "BTC", name: "Bitcoin", thumb: "https://coin-images.coingecko.com/coins/images/1/thumb/bitcoin.png", market_cap_rank: 1, price_btc: 1.0 } },
          { item: { id: "ethereum", symbol: "ETH", name: "Ethereum", thumb: "https://coin-images.coingecko.com/coins/images/279/thumb/ethereum.png", market_cap_rank: 2, price_btc: 0.05 } },
          { item: { id: "solana", symbol: "SOL", name: "Solana", thumb: "https://coin-images.coingecko.com/coins/images/4128/thumb/solana.png", market_cap_rank: 5, price_btc: 0.002 } },
        ]);
      });
  }, []);

  useEffect(() => {
    if (!currentSymbol) return;
    setLoadingComparison(true);
    fetch(`/api/v1/market/compare/${currentSymbol}`)
      .then(res => res.json())
      .then(d => {
        // Mock data for demo if backend returns nulls (e.g. due to network issues)
        if (!d.binance_price && !d.coingecko_price) {
           setComparisonData({
             binance_price: ticker ? ticker.price : 67154.98,
             coingecko_price: ticker ? ticker.price * 0.9998 : 67141.55,
             price_diff: ticker ? ticker.price * 0.0002 : 13.43,
             price_diff_percent: 0.02
           });
        } else {
           setComparisonData(d);
        }
      })
      .catch(() => {
         // Mock on error
         setComparisonData({
             binance_price: 67154.98,
             coingecko_price: 67141.55,
             price_diff: 13.43,
             price_diff_percent: 0.02
         });
      })
      .finally(() => setLoadingComparison(false));
  }, [currentSymbol, ticker]);

  // Cooldown & Cache refs
  const analysisCache = useRef<AnalysisCache>({});
  const cooldownTracker = useRef<CooldownTracker>({});
  const [cooldownRemaining, setCooldownRemaining] = useState<Record<string, number>>({});

  // WebSocket ref
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectAttempts = useRef(0);
  const lastTickerRef = useRef<Ticker | null>(null); // 保留最后的价格数据

  // Agent State
  const [agents, setAgents] = useState([
    { id: "trend", name: "趋势跟踪Agent", type: "trend", status: "运行中", provider: "openai", action: "分析趋势", icon: TrendingUp, logs: "点击「分析」开始", analyzing: false, isStreaming: false, thinkingContent: "", outputContent: "", thinkCollapsed: true, profit: "+$145.20", winRate: "...", winRateLoading: true, color: "blue" },
    { id: "mean_reversion", name: "均值回归Agent", type: "mean_reversion", status: "运行中", provider: "ollama", action: "寻找反转", icon: Activity, logs: "点击「分析」开始", analyzing: false, isStreaming: false, thinkingContent: "", outputContent: "", thinkCollapsed: true, profit: "+$32.50", winRate: "...", winRateLoading: true, color: "purple" },
    { id: "risk", name: "风险管理Agent", type: "risk", status: "运行中", provider: "openai", action: "监控风险", icon: Shield, logs: "点击「分析」开始", analyzing: false, isStreaming: false, thinkingContent: "", outputContent: "", thinkCollapsed: true, profit: "--", winRate: "...", winRateLoading: true, color: "orange" },
  ]);
  const [configuringAgent, setConfiguringAgent] = useState<string | null>(null);


  const symbols = [
    { value: "BTCUSDT", label: "BTC/USDT" }, { value: "ETHUSDT", label: "ETH/USDT" },
    { value: "SOLUSDT", label: "SOL/USDT" }, { value: "BNBUSDT", label: "BNB/USDT" },
    { value: "DOGEUSDT", label: "DOGE/USDT" }, { value: "XRPUSDT", label: "XRP/USDT" },
  ];
  const intervals = [
    { value: "1m", label: "1分钟" }, { value: "5m", label: "5分钟" },
    { value: "15m", label: "15分钟" }, { value: "1h", label: "1小时" },
    { value: "4h", label: "4小时" }, { value: "1d", label: "1天" },
  ];
  const aiProviders = [
    { value: "openai", label: "Custom Model (Aliyun Qwen)" },
    { value: "ollama", label: "Ollama (Local)" },
  ];

  // ── Fetch balance & positions ──────────────────────────────────────────────
  const fetchBalance = useCallback(async () => {
    try {
      const res = await fetch("/api/v1/trading/balance");
      if (res.ok) setBalance(await res.json());
    } catch { /* ignore */ }
  }, []);

  const fetchPositions = useCallback(async () => {
    setPositionsLoading(true);
    try {
      const res = await fetch("/api/v1/trading/positions");
      if (res.ok) {
        const data = await res.json();
        setPositions(data.positions || []);
      }
    } catch { /* ignore */ }
    finally { setPositionsLoading(false); }
  }, []);

  const fetchRiskStatus = useCallback(async () => {
    try {
      const res = await fetch("/api/v1/trading/risk-status");
      if (res.ok) setRiskStatus(await res.json());
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    fetchBalance();
    fetchPositions();
    fetchRiskStatus();
    const t = setInterval(() => { fetchBalance(); fetchPositions(); fetchRiskStatus(); }, 15000);
    return () => clearInterval(t);
  }, [fetchBalance, fetchPositions, fetchRiskStatus]);

  // ── WebSocket ──────────────────────────────────────────────────────────────
  const connectWS = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    setWsStatus("connecting");
    const wsUrl = getWsUrl();
    console.log("Connecting to WebSocket:", wsUrl);
    
    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setWsStatus("connected");
        ws.send(JSON.stringify({ action: "subscribe", symbol: currentSymbol }));
      };

      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data);
          if (msg.type === "ticker") {
            const tickerData = {
              symbol:         msg.symbol,
              price:          msg.price,
              change_24h:     msg.change_24h,
              change_percent: msg.change_percent || msg.change_pct,
              volume:         msg.volume,
              high_24h:       msg.high_24h,
              low_24h:        msg.low_24h,
            };
            // 保存最后的价格数据，断连时保留显示
            lastTickerRef.current = tickerData;
            setTicker(tickerData);
            // 重连成功后重置计数
            reconnectAttempts.current = 0;
          }
        } catch { /* ignore */ }
      };

      ws.onerror = (e) => { 
        // 仅在非关闭状态下记录错误，避免开发环境热重载时的干扰
        if (ws.readyState !== WebSocket.CLOSED && ws.readyState !== WebSocket.CLOSING) {
          console.warn("WebSocket error:", e);
        }
        setWsStatus("disconnected");
        // 增加重连计数
        reconnectAttempts.current += 1;
      };
      ws.onclose = () => {
        setWsStatus("disconnected");
        // 断连时不清除 ticker 数据，保留最后已知价格显示
        // lastTickerRef.current 已在 onerror 之前保存
        // 只有在未卸载且非主动关闭时才重连
        if (wsRef.current === ws) {
          const delay = Math.min(3000 * Math.pow(1.5, reconnectAttempts.current), 30000);
          reconnectTimer.current = setTimeout(() => connectWS(), delay);
        }
      };
    } catch (e) {
      console.warn("Failed to create WebSocket:", e);
      setWsStatus("disconnected");
      reconnectTimer.current = setTimeout(() => connectWS(), 5000);
    }
  }, [currentSymbol]);

  // Subscribe to new symbol on change
  useEffect(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: "subscribe", symbol: currentSymbol }));
    }
  }, [currentSymbol]);

  useEffect(() => {
    connectWS();
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      if (wsRef.current) {
        // 清理监听器以防止卸载后状态更新导致的内存泄漏和报错
        wsRef.current.onopen = null;
        wsRef.current.onclose = null;
        wsRef.current.onerror = null;
        wsRef.current.onmessage = null;
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [connectWS]);

  // ── Ollama status ──────────────────────────────────────────────────────────
  useEffect(() => {
    fetch("/api/v1/market/ollama/status").then(r => r.ok ? r.json() : null).then(d => {
      if (d) setOllamaStatus({ ...d, checked: true });
    }).catch(() => setOllamaStatus({ online: false, checked: true }));
  }, []);

  // ── Agent Win-Rate (from backtest engine) ──────────────────────────────────
  const fetchAgentWinRates = useCallback(async (symbol: string) => {
    // 并发为所有 Agent 发起轻量回测，获取真实胜率
    const agentIds = Object.keys(AGENT_STRATEGY_MAP);

    // 先标记为 loading
    setAgents(p => p.map(a => agentIds.includes(a.id) ? { ...a, winRate: "...", winRateLoading: true } : a));

    await Promise.allSettled(
      agentIds.map(async (agentId) => {
        const cfg = AGENT_STRATEGY_MAP[agentId];
        try {
          const res = await fetch("/api/v1/strategy/backtest/run", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              strategy_type:   cfg.strategy_type,
              symbol:          symbol,
              interval:        cfg.interval,
              limit:           cfg.limit,
              initial_capital: 10000,
              params:          cfg.params,
            }),
          });
          if (res.ok) {
            const data = await res.json();
            const winRate = data.metrics?.win_rate;
            if (winRate !== undefined) {
              setAgents(p => p.map(a =>
                a.id === agentId
                  ? { ...a, winRate: `${winRate.toFixed(1)}%`, winRateLoading: false }
                  : a
              ));
            } else {
              setAgents(p => p.map(a => a.id === agentId ? { ...a, winRate: "--", winRateLoading: false } : a));
            }
          } else {
            setAgents(p => p.map(a => a.id === agentId ? { ...a, winRate: "--", winRateLoading: false } : a));
          }
        } catch {
          setAgents(p => p.map(a => a.id === agentId ? { ...a, winRate: "--", winRateLoading: false } : a));
        }
      })
    );
  }, []);

  // 初始化 & 切换交易对时刷新胜率
  useEffect(() => {
    fetchAgentWinRates(currentSymbol);
  }, [currentSymbol, fetchAgentWinRates]);

  // ── Cooldown timer ─────────────────────────────────────────────────────────
  useEffect(() => {
    const timer = setInterval(() => {
      const now = Date.now();
      const next: Record<string, number> = {};
      let any = false;
      Object.entries(cooldownTracker.current).forEach(([id, t]) => {
        const r = Math.max(0, COOLDOWN_SECONDS - Math.floor((now - t) / 1000));
        next[id] = r;
        if (r > 0) any = true;
      });
      setCooldownRemaining(any ? next : {});
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  // ── Agent Analysis ─────────────────────────────────────────────────────────
  interface Agent {
    id: string;
    name: string;
    type: string;
    status: string;
    provider: string;
    action: string;
    icon: React.ComponentType<{ className?: string }>;
    logs: string;
    analyzing: boolean;
    isStreaming: boolean;
    thinkingContent: string;
    outputContent: string;
    thinkCollapsed: boolean;
    profit: string;
    winRate: string;
    winRateLoading: boolean;
    color: string;
  }

  const fetchAgentAnalysis = useCallback(async (agent: Agent, forceRefresh = false) => {
    const cacheKey = `${agent.id}-${currentSymbol}`;
    const now = Date.now();

    const lastTime = cooldownTracker.current[agent.id] || 0;
    if (!forceRefresh && (now - lastTime) / 1000 < COOLDOWN_SECONDS && lastTime > 0) {
      const r = Math.ceil(COOLDOWN_SECONDS - (now - lastTime) / 1000);
      setAgents(p => p.map(a => a.id === agent.id ? { ...a, logs: `⏳ 冷却中，${r}秒后可再次分析` } : a));
      return;
    }

    const cached = analysisCache.current[cacheKey];
    if (!forceRefresh && cached && now - cached.timestamp < 5 * 60 * 1000) {
      setAgents(p => p.map(a => a.id === agent.id ? { ...a, logs: cached.result, outputContent: cached.outputContent ?? cached.result, thinkingContent: cached.thinkingContent ?? "", analyzing: false, isStreaming: false } : a));
      return;
    }

    if (agent.provider === "ollama") {
      setAgents(p => p.map(a => a.id === agent.id ? { ...a, analyzing: true, isStreaming: true, logs: "AI 正在思考中...", thinkingContent: "", outputContent: "", thinkCollapsed: true } : a));
      try {
        const res = await fetch(`/api/v1/market/agent-analysis-stream/${agent.type}/${currentSymbol}?provider=${agent.provider}&interval=1h`);
        if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buf = "", inThink = false, thinkBuf = "", outputBuf = "", tagBuf = "";

        const processChunk = (text: string) => {
          const input = tagBuf + text; tagBuf = "";
          let i = 0;
          while (i < input.length) {
            if (inThink) {
              const ci = input.indexOf("</think>", i);
              if (ci !== -1) { thinkBuf += input.slice(i, ci); inThink = false; i = ci + 8; }
              else { thinkBuf += input.slice(i); i = input.length; }
            } else {
              const oi = input.indexOf("<think>", i);
              if (oi !== -1) { outputBuf += input.slice(i, oi); inThink = true; i = oi + 7; }
              else { outputBuf += input.slice(i); i = input.length; }
            }
          }
        };

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          const lines = buf.split("\n"); buf = lines.pop() ?? "";
          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            try {
              const p = JSON.parse(line.slice(6).trim());
              if (p.done) {
                cooldownTracker.current[agent.id] = Date.now();
                setCooldownRemaining(x => ({ ...x, [agent.id]: COOLDOWN_SECONDS }));
                const fo = outputBuf.trim(), ft = thinkBuf.trim();
                analysisCache.current[cacheKey] = { result: fo, outputContent: fo, thinkingContent: ft, timestamp: Date.now() };
                setAgents(x => x.map(a => a.id === agent.id ? { ...a, analyzing: false, isStreaming: false, logs: fo, outputContent: fo, thinkingContent: ft } : a));
                return;
              }
              if (p.error) { 
                setAgents(x => x.map(a => a.id === agent.id ? { ...a, analyzing: false, isStreaming: false, logs: `分析失败: ${p.error}` } : a)); 
                // 失败时清除冷却，允许立即重试
                delete cooldownTracker.current[agent.id];
                return; 
              }
              if (p.chunk) { processChunk(p.chunk); setAgents(x => x.map(a => a.id === agent.id ? { ...a, thinkingContent: thinkBuf, outputContent: outputBuf, logs: outputBuf } : a)); }
            } catch { /* ignore */ }
          }
        }
      } catch {
        setAgents(p => p.map(a => a.id === agent.id ? { ...a, analyzing: false, isStreaming: false, logs: "分析失败: 网络错误" } : a));
        // 失败时清除冷却，允许立即重试
        delete cooldownTracker.current[agent.id];
      }
      return;
    }

    setAgents(p => p.map(a => a.id === agent.id ? { ...a, analyzing: true, logs: "AI 正在思考中..." } : a));
    try {
      const res = await fetch(`/api/v1/market/agent-analysis/${agent.type}/${currentSymbol}?provider=${agent.provider}&interval=1h`);
      if (res.ok) {
        const data = await res.json();
        analysisCache.current[cacheKey] = { result: data.analysis, outputContent: data.analysis, thinkingContent: "", timestamp: Date.now() };
        cooldownTracker.current[agent.id] = Date.now();
        setCooldownRemaining(x => ({ ...x, [agent.id]: COOLDOWN_SECONDS }));
        setAgents(p => p.map(a => a.id === agent.id ? { ...a, logs: data.analysis, outputContent: data.analysis, analyzing: false } : a));
      } else {
        setAgents(p => p.map(a => a.id === agent.id ? { ...a, logs: "分析失败: 服务异常", analyzing: false } : a));
        // 失败时清除冷却，允许立即重试
        delete cooldownTracker.current[agent.id];
      }
    } catch {
      setAgents(p => p.map(a => a.id === agent.id ? { ...a, logs: "分析失败: 网络错误", analyzing: false } : a));
      // 失败时清除冷却，允许立即重试
      delete cooldownTracker.current[agent.id];
    }
  }, [currentSymbol]);

  const handleProviderChange = (agentId: string, newProvider: string) => {
    setAgents(p => p.map(a => a.id === agentId ? { ...a, provider: newProvider } : a));
    Object.keys(analysisCache.current).filter(k => k.startsWith(agentId)).forEach(k => delete analysisCache.current[k]);
  };

  const toggleAgentStatus = (agentId: string) =>
    setAgents(p => p.map(a => a.id === agentId ? { ...a, status: a.status === "运行中" ? "暂停" : "运行中" } : a));

  const toggleThink = (agentId: string) =>
    setAgents(p => p.map(a => a.id === agentId ? { ...a, thinkCollapsed: !a.thinkCollapsed } : a));

  const handleClosePosition = async (pos: Position) => {
    try {
      await fetch("/api/v1/trading/orders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: pos.symbol, side: "SELL", order_type: "MARKET", quantity: pos.quantity }),
      });
      fetchPositions();
      fetchBalance();
    } catch { /* ignore */ }
  };

  const handleCloseAll = async () => {
    await fetch("/api/v1/trading/positions/close-all", { method: "POST" });
    fetchPositions();
    fetchBalance();
  };

  const formatCurrency = (v: number) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(v);
  const formatNumber   = (v: number) => new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(v);

  return (
    <div className="min-h-screen bg-slate-950">
      {/* ── Header ── */}
      <header className="border-b border-slate-800 bg-slate-900/50 backdrop-blur-sm sticky top-0 z-40">
        <div className="container mx-auto px-4 py-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 bg-gradient-to-br from-blue-500 to-purple-600 rounded-xl flex items-center justify-center">
                <BarChart3 className="w-5 h-5 text-white" />
              </div>
              <div>
                <h1 className="text-lg font-bold text-slate-100">QuantAgent OS</h1>
                <p className="text-[10px] text-slate-400">AI-Native Quantitative Trading</p>
              </div>
            </div>

            <nav className="hidden md:flex items-center gap-1">
              <Link href="/dashboard" className="px-3 py-1.5 text-sm text-blue-400 bg-blue-500/10 rounded-lg border border-blue-500/20 font-medium">
                仪表盘
              </Link>
              <Link href="/trades" className="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-100 hover:bg-slate-800 rounded-lg transition-all flex items-center gap-1.5">
                <Activity className="w-4 h-4" /> 交易流水
              </Link>
              <Link href="/analytics" className="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-100 hover:bg-slate-800 rounded-lg transition-all flex items-center gap-1.5">
                <BarChart className="w-4 h-4" /> 性能分析
              </Link>
              <Link href="/backtest" className="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-100 hover:bg-slate-800 rounded-lg transition-all flex items-center gap-1.5">
                回测
              </Link>
              <Link href="/replay" className="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-100 hover:bg-slate-800 rounded-lg transition-all flex items-center gap-1.5">
                <History className="w-4 h-4" /> 历史回放
              </Link>
              <Link href="/terminal" className="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-100 hover:bg-slate-800 rounded-lg transition-all flex items-center gap-1.5">
                终端
              </Link>
            </nav>

            <div className="flex items-center gap-3">
              {/* Balance chip */}
              {balance && (
                <div className="hidden sm:flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 rounded-lg border border-slate-700">
                  <Wallet className="w-3.5 h-3.5 text-green-400" />
                  <span className="text-green-400 text-xs font-mono font-bold">
                    ${balance.total_balance.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                  </span>
                </div>
              )}

              {/* Symbol Selector */}
              <Select key="symbol-select" value={currentSymbol} onValueChange={setCurrentSymbol}>
                <SelectTrigger className="w-[140px] bg-slate-800 border-slate-700 text-slate-100 h-8 text-sm">
                  <SelectValue placeholder="选择币种" />
                </SelectTrigger>
                <SelectContent className="bg-slate-800 border-slate-700">
                  {symbols.map(s => (
                    <SelectItem key={s.value} value={s.value} className="text-slate-100 focus:bg-slate-700 focus:text-slate-100 cursor-pointer">{s.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>

              {/* WS status */}
              <Badge variant="outline" className={
                wsStatus === "connected"    ? "bg-green-500/10 text-green-400 border-green-500/20" :
                wsStatus === "connecting"   ? "bg-yellow-500/10 text-yellow-400 border-yellow-500/20" :
                                              "bg-red-500/10 text-red-400 border-red-500/20"
              }>
                <span className={`w-2 h-2 rounded-full mr-2 inline-block ${wsStatus === "connected" ? "bg-green-500 animate-pulse" : wsStatus === "connecting" ? "bg-yellow-500 animate-pulse" : "bg-red-500"}`} />
                {wsStatus === "connected" ? "实时" : wsStatus === "connecting" ? "连接中" : `断线${reconnectAttempts.current > 0 ? ` (重连${reconnectAttempts.current})` : ""}`}
              </Badge>

              {/* Order Button */}
              <Button
                size="sm"
                onClick={() => setShowOrderPanel(true)}
                className="h-8 bg-blue-600 hover:bg-blue-500 text-white text-xs px-3 rounded-lg"
              >
                <Plus className="w-3.5 h-3.5 mr-1" /> 下单
              </Button>
            </div>
          </div>
        </div>
      </header>

      {/* ── Main ── */}
      <main className="container mx-auto px-4 py-6">
        {/* Stats */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <Card className="bg-gradient-to-br from-slate-900 to-slate-800/50 border-slate-700/50 hover:border-blue-500/30 transition-all">
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs text-slate-400 uppercase tracking-wider">{currentSymbol} 价格</p>
                  <p className="text-2xl font-bold text-slate-100 mt-1">
                    {ticker ? formatCurrency(ticker.price) : "—"}
                  </p>
                </div>
                <div className="w-12 h-12 bg-blue-500/10 rounded-xl flex items-center justify-center border border-blue-500/20">
                  <DollarSign className="w-6 h-6 text-blue-400" />
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="bg-gradient-to-br from-slate-900 to-slate-800/50 border-slate-700/50 hover:border-green-500/30 transition-all">
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs text-slate-400 uppercase tracking-wider">24h 涨跌幅</p>
                  <p className={`text-2xl font-bold mt-1 ${(ticker?.change_percent ?? 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                    {ticker ? `${ticker.change_percent >= 0 ? "+" : ""}${ticker.change_percent.toFixed(2)}%` : "—"}
                  </p>
                </div>
                <div className={`w-12 h-12 rounded-xl flex items-center justify-center border ${(ticker?.change_percent ?? 0) >= 0 ? "bg-green-500/10 border-green-500/20" : "bg-red-500/10 border-red-500/20"}`}>
                  {(ticker?.change_percent ?? 0) >= 0
                    ? <TrendingUp className="w-6 h-6 text-green-400" />
                    : <TrendingDown className="w-6 h-6 text-red-400" />}
                </div>
              </div>
              <p className={`text-xs mt-2 ${(ticker?.change_24h ?? 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                {ticker ? `${ticker.change_24h >= 0 ? "+" : ""}${formatNumber(ticker.change_24h)}` : ""}
              </p>
            </CardContent>
          </Card>

          <Card className="bg-gradient-to-br from-slate-900 to-slate-800/50 border-slate-700/50 hover:border-purple-500/30 transition-all">
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs text-slate-400 uppercase tracking-wider">24h 成交量</p>
                  <p className="text-2xl font-bold text-slate-100 mt-1">
                    {ticker ? formatNumber(ticker.volume) : "—"}
                  </p>
                </div>
                <div className="w-12 h-12 bg-purple-500/10 rounded-xl flex items-center justify-center border border-purple-500/20">
                  <BarChart2 className="w-6 h-6 text-purple-400" />
                </div>
              </div>
              <p className="text-xs text-slate-500 mt-2">USDT</p>
            </CardContent>
          </Card>

          <Card className="bg-gradient-to-br from-slate-900 to-slate-800/50 border-slate-700/50 hover:border-orange-500/30 transition-all">
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs text-slate-400 uppercase tracking-wider">模拟账户</p>
                  <p className="text-2xl font-bold text-slate-100 mt-1">
                    {balance ? `$${(balance.total_balance / 1000).toFixed(1)}K` : "—"}
                  </p>
                </div>
                <div className="w-12 h-12 bg-orange-500/10 rounded-xl flex items-center justify-center border border-orange-500/20">
                  <Wallet className="w-6 h-6 text-orange-400" />
                </div>
              </div>
              <p className="text-xs text-green-400 mt-2">虚拟 USDT</p>
            </CardContent>
          </Card>
        </div>

        {/* Risk Monitor Status */}
        {riskStatus && (
          <div className="mb-6 grid grid-cols-2 md:grid-cols-4 gap-4">
             <div className={`p-3 rounded-xl border ${riskStatus.kill_switch_active ? 'bg-red-500/20 border-red-500 text-red-400' : 'bg-green-500/10 border-green-500/20 text-green-400'} flex items-center gap-3`}>
                <Shield className="w-5 h-5" />
                <div>
                   <p className="text-[10px] uppercase font-bold">Kill Switch</p>
                   <p className="text-sm font-bold">{riskStatus.kill_switch_active ? "ACTIVATED" : "SAFE"}</p>
                </div>
             </div>
             <div className="p-3 bg-slate-900/50 rounded-xl border border-slate-700/50 flex items-center gap-3">
                <Activity className="w-5 h-5 text-blue-400" />
                <div>
                   <p className="text-[10px] text-slate-400 uppercase">Drawdown</p>
                   <p className={`text-sm font-bold ${riskStatus.drawdown_breached ? 'text-red-400' : 'text-slate-200'}`}>
                      {riskStatus.total_drawdown_pct}% <span className="text-[9px] text-slate-500">/ {riskStatus.drawdown_limit_pct}%</span>
                   </p>
                </div>
             </div>
             <div className="p-3 bg-slate-900/50 rounded-xl border border-slate-700/50 flex items-center gap-3">
                <BarChart2 className="w-5 h-5 text-purple-400" />
                <div>
                   <p className="text-[10px] text-slate-400 uppercase">Daily Loss</p>
                   <p className={`text-sm font-bold ${riskStatus.daily_loss_breached ? 'text-red-400' : 'text-slate-200'}`}>
                      ${riskStatus.daily_pnl} <span className="text-[9px] text-slate-500">Limit: {riskStatus.daily_loss_limit_pct}%</span>
                   </p>
                </div>
             </div>
             <div className="p-3 bg-slate-900/50 rounded-xl border border-slate-700/50 flex items-center gap-3">
                <Zap className="w-5 h-5 text-yellow-400" />
                <div>
                   <p className="text-[10px] text-slate-400 uppercase">Leverage Limit</p>
                   <p className="text-sm font-bold text-slate-200">{riskStatus.max_leverage}x</p>
                </div>
             </div>
          </div>
        )}

        {/* Price Comparison */}
        <Card className="bg-gradient-to-br from-slate-900 to-slate-800/50 border-slate-700/50 mb-6">
            <CardContent className="p-4 flex flex-wrap items-center justify-between gap-4 text-sm">
              <div className="flex items-center gap-2">
                <span className="text-slate-400 font-bold uppercase">Price Comparison ({currentSymbol})</span>
                {loadingComparison && <RefreshCw className="w-3 h-3 animate-spin text-slate-500" />}
              </div>
              
              {comparisonData ? (
                <div className="flex items-center gap-6">
                  <div className="flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-2">
                    <span className="text-slate-500 text-xs uppercase">Binance</span>
                    <span className="font-mono text-slate-200 font-bold">
                      ${comparisonData.binance_price ? formatNumber(comparisonData.binance_price) : "—"}
                    </span>
                  </div>
                  <div className="flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-2">
                    <span className="text-slate-500 text-xs uppercase">CoinGecko</span>
                    <span className="font-mono text-slate-200 font-bold">
                      ${comparisonData.coingecko_price ? formatNumber(comparisonData.coingecko_price) : "—"}
                    </span>
                  </div>
                  <div className="flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-2 pl-4 border-l border-slate-700">
                    <span className="text-slate-500 text-xs uppercase">Spread</span>
                    <span className={`font-mono font-bold ${(comparisonData.price_diff ?? 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                      {(comparisonData.price_diff ?? 0) >= 0 ? "+" : ""}{comparisonData.price_diff ? formatNumber(comparisonData.price_diff) : "0.00"}
                    </span>
                    <span className={`text-xs ${(comparisonData.price_diff_percent ?? 0) >= 0 ? "text-green-400/70" : "text-red-400/70"}`}>
                      ({(comparisonData.price_diff_percent ?? 0).toFixed(4)}%)
                    </span>
                  </div>
                </div>
              ) : (
                <div className="text-slate-500 text-xs">暂无数据</div>
              )}
            </CardContent>
          </Card>

        {/* Chart */}
        <div className="mb-6 relative">
          <div className="absolute top-4 right-4 z-10">
            <Select key="interval-select" value={currentInterval} onValueChange={setCurrentInterval}>
              <SelectTrigger className="w-24 bg-slate-800 border-slate-700 text-slate-100">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-slate-800 border-slate-700">
                {intervals.map(i => (
                  <SelectItem key={i.value} value={i.value} className="text-slate-100 focus:bg-slate-700 focus:text-slate-100 cursor-pointer">{i.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <TradingViewChart symbol={currentSymbol} interval={currentInterval} />
        </div>

        {/* Trending Coins */}
        {trendingCoins.length > 0 && (
          <div className="mb-6">
            <h3 className="text-sm font-bold text-slate-400 uppercase tracking-wider mb-3 flex items-center gap-2">
              <TrendingUp className="w-4 h-4" /> Trending Coins (CoinGecko)
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4">
              {trendingCoins.slice(0, 4).map((coin, idx) => (
                <div key={idx} className="flex items-center gap-3 p-3 bg-slate-900/50 rounded-xl border border-slate-800/50 hover:border-slate-700 transition-all">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={coin.item.thumb} alt={coin.item.name} width={32} height={32} className="rounded-full" loading="lazy" />
                  <div>
                    <p className="text-sm font-bold text-slate-200">{coin.item.name}</p>
                    <p className="text-xs text-slate-500">#{coin.item.market_cap_rank} · {coin.item.symbol}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="space-y-6">
          {/* ── Positions ── */}
          <Card className="bg-gradient-to-br from-slate-900 to-slate-800/30 border-slate-700/50">
            <CardHeader className="pb-4">
              <div className="flex items-center justify-between">
                <CardTitle className="text-slate-100 flex items-center gap-2">
                  <div className="w-8 h-8 bg-blue-500/10 rounded-lg flex items-center justify-center border border-blue-500/20">
                    <Activity className="w-4 h-4 text-blue-400" />
                  </div>
                  当前持仓
                  {positions.length > 0 && (
                    <Badge variant="outline" className="text-[10px] bg-blue-500/10 text-blue-400 border-blue-500/20 ml-1">
                      {positions.length}
                    </Badge>
                  )}
                </CardTitle>
                <div className="flex items-center gap-2">
                  <Button variant="ghost" size="sm" className="h-7 text-xs text-slate-400 hover:text-slate-100 px-2" onClick={fetchPositions}>
                    <RefreshCw className="w-3 h-3 mr-1" /> 刷新
                  </Button>
                  {positions.length > 0 && (
                    <Button variant="outline" size="sm" className="h-7 text-xs border-red-500/30 text-red-400 hover:bg-red-500/10 hover:text-red-300" onClick={handleCloseAll}>
                      一键平仓
                    </Button>
                  )}
                </div>
              </div>
            </CardHeader>
            <CardContent className="pt-0">
              {positionsLoading ? (
                <div className="flex items-center justify-center py-8 text-slate-500 text-sm">
                  <RefreshCw className="w-4 h-4 animate-spin mr-2" /> 加载持仓中...
                </div>
              ) : positions.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-10 text-slate-500">
                  <Activity className="w-10 h-10 mb-3 opacity-30" />
                  <p className="text-sm">暂无持仓</p>
                  <p className="text-xs text-slate-600 mt-1">点击右上角「下单」开始模拟交易</p>
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  {positions.map((pos, idx) => (
                    <div key={idx} className="group relative p-4 bg-gradient-to-br from-slate-800/80 to-slate-900/80 rounded-xl border border-slate-700/50 hover:border-slate-500/50 transition-all hover:shadow-lg">
                      <div className="flex items-center justify-between mb-3">
                        <div className="flex items-center gap-2">
                          <div className="w-8 h-8 bg-green-500/15 text-green-400 border border-green-500/20 rounded-lg flex items-center justify-center">
                            <TrendingUp className="w-4 h-4" />
                          </div>
                          <div>
                            <div className="flex items-center gap-1.5">
                              <span className="font-bold text-slate-100">{pos.symbol}</span>
                              <Badge variant="outline" className="text-[9px] px-1 py-0 bg-green-500/10 text-green-400 border-green-500/20">LONG</Badge>
                            </div>
                            <p className="text-[10px] text-slate-500">持仓 {Number(pos.quantity).toFixed(6)}</p>
                          </div>
                        </div>
                        <div className="text-right">
                          <p className={`text-lg font-bold ${pos.pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                            {pos.pnl >= 0 ? "+" : ""}${Number(pos.pnl).toFixed(2)}
                          </p>
                          <div className={`inline-flex items-center px-1.5 rounded text-[10px] font-medium ${pos.pnl >= 0 ? "bg-green-500/10 text-green-400" : "bg-red-500/10 text-red-400"}`}>
                            {pos.pnl_pct >= 0 ? "+" : ""}{Number(pos.pnl_pct).toFixed(2)}%
                          </div>
                        </div>
                      </div>

                      <div className="grid grid-cols-3 gap-1 p-2 bg-slate-900/50 rounded-lg border border-slate-800/50 text-center">
                        <div>
                          <p className="text-slate-500 text-[9px] uppercase">开仓</p>
                          <p className="text-slate-200 font-medium text-xs">${Number(pos.avg_price).toFixed(2)}</p>
                        </div>
                        <div className="border-x border-slate-800/50">
                          <p className="text-slate-500 text-[9px] uppercase">标记</p>
                          <p className="text-blue-400 font-medium text-xs">${Number(pos.mark_price).toFixed(2)}</p>
                        </div>
                        <div>
                          <p className="text-slate-500 text-[9px] uppercase">数量</p>
                          <p className="text-slate-300 font-medium text-xs">{Number(pos.quantity).toFixed(4)}</p>
                        </div>
                      </div>

                      <div className="mt-2 flex justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <Button
                          variant="ghost" size="sm"
                          className="h-6 text-[10px] text-red-400 hover:bg-red-500/10 px-2"
                          onClick={() => handleClosePosition(pos)}
                        >
                          平仓
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* ── AI Agents ── */}
          <Card className="bg-gradient-to-br from-slate-900 to-slate-800/30 border-slate-700/50">
            <CardHeader className="pb-4">
              <CardTitle className="text-slate-100 flex items-center gap-2">
                <div className="w-8 h-8 bg-purple-500/10 rounded-lg flex items-center justify-center border border-purple-500/20">
                  <Brain className="w-4 h-4 text-purple-400" />
                </div>
                AI Agent 状态
                <div className="w-2 h-2 bg-green-400 rounded-full animate-pulse ml-1" />
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              {ollamaStatus.checked && !ollamaStatus.online && agents.some(a => a.provider === "ollama") && (
                <div className="mb-4 p-3 bg-orange-500/10 border border-orange-500/30 rounded-lg flex items-start gap-2">
                  <WifiOff className="w-4 h-4 text-orange-400 mt-0.5 shrink-0" />
                  <div className="text-xs text-orange-300">
                    <p className="font-semibold mb-1">Ollama 本地服务未运行</p>
                    <a href="https://ollama.com/download" target="_blank" rel="noopener noreferrer" className="text-blue-400 underline">下载 Ollama</a>
                    <span className="ml-2 text-orange-400/70">启动后运行：<code className="bg-slate-800 px-1 rounded">ollama run qwen3:8b</code></span>
                  </div>
                </div>
              )}

              <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                {agents.map((agent) => {
                  const remaining = cooldownRemaining[agent.id] || 0;
                  const isOllamaOffline = agent.provider === "ollama" && ollamaStatus.checked && !ollamaStatus.online;
                  const canAnalyze = agent.status === "运行中" && !agent.analyzing && remaining === 0 && !isOllamaOffline;
                  const hasError = agent.logs.includes("失败") || isOllamaOffline;
                  const colorMap: Record<string, { bg: string; text: string; border: string; glow: string }> = {
                    blue:   { bg: "bg-blue-500/10",   text: "text-blue-400",   border: "border-blue-500/20",   glow: "hover:shadow-blue-500/10" },
                    purple: { bg: "bg-purple-500/10", text: "text-purple-400", border: "border-purple-500/20", glow: "hover:shadow-purple-500/10" },
                    orange: { bg: "bg-orange-500/10", text: "text-orange-400", border: "border-orange-500/20", glow: "hover:shadow-orange-500/10" },
                  };
                  const s = colorMap[agent.color] || colorMap.blue;

                  return (
                    <div key={agent.id} className={`group relative bg-gradient-to-br from-slate-800/80 to-slate-900/80 rounded-xl border ${hasError ? "border-red-500/30" : "border-slate-700/50"} hover:border-slate-500/50 transition-all hover:shadow-lg ${s.glow} flex flex-col`}>
                      <div className="p-3">
                        <div className="flex items-center gap-3">
                          <div className={`w-10 h-10 ${s.bg} rounded-lg flex items-center justify-center border ${s.border} shrink-0`}>
                            <agent.icon className={`w-5 h-5 ${s.text}`} />
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center justify-between gap-1">
                              <p className="font-bold text-slate-100 text-sm truncate">{agent.name}</p>
                              <Badge variant="outline" className={`text-[9px] px-1 py-0 ${agent.status === "运行中" ? "bg-green-500/10 text-green-400 border-green-500/20" : "bg-slate-500/10 text-slate-400 border-slate-500/20"}`}>
                                {agent.status}
                              </Badge>
                            </div>
                            <div className="flex items-center gap-2 mt-0.5">
                              <span className="text-[10px] text-slate-400 truncate">{aiProviders.find(p => p.value === agent.provider)?.label || agent.provider}</span>
                              {agent.winRateLoading ? (
                                <span className="text-[10px] text-slate-500">胜率: <span className="text-slate-500 animate-pulse">计算中…</span></span>
                              ) : agent.winRate !== "--" ? (
                                <span className="text-[10px] text-slate-500">
                                  胜率: <span className={parseFloat(agent.winRate) >= 50 ? "text-green-400" : "text-red-400"}>{agent.winRate}</span>
                                </span>
                              ) : null}
                            </div>
                          </div>
                        </div>
                      </div>

                      <div className="flex-1 flex flex-col">
                        {configuringAgent === agent.id && (
                          <div className="mx-3 mb-2 p-2 bg-slate-900 rounded-lg border border-slate-800">
                            <div className="text-[10px] text-slate-400 mb-1">选择模型:</div>
                            <Select value={agent.provider} onValueChange={v => handleProviderChange(agent.id, v)}>
                              <SelectTrigger className="w-full h-7 bg-slate-800 border-slate-700 text-slate-100 text-[10px]">
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent className="bg-slate-800 border-slate-700">
                                {aiProviders.map(p => (
                                  <SelectItem key={p.value} value={p.value} className="text-[10px] text-slate-100 cursor-pointer focus:bg-slate-700">{p.label}</SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          </div>
                        )}

                        {agent.provider === "ollama" && agent.thinkingContent && (
                          <div className="mx-3 mb-1">
                            <button onClick={() => toggleThink(agent.id)} className="flex items-center gap-1 text-[9px] text-amber-400/70 hover:text-amber-400 w-full">
                              <Brain className="w-3 h-3 shrink-0" /> <span>思考过程</span>
                              {agent.thinkCollapsed ? <ChevronDown className="w-3 h-3 ml-auto" /> : <ChevronUp className="w-3 h-3 ml-auto" />}
                            </button>
                            {!agent.thinkCollapsed && (
                              <div className="mt-1 p-2 bg-amber-500/5 border border-amber-500/15 rounded-lg max-h-[200px] overflow-y-auto">
                                <p className="text-[9px] text-amber-300/60 italic whitespace-pre-wrap">{agent.thinkingContent}</p>
                              </div>
                            )}
                          </div>
                        )}

                        <div className="mx-3 mb-2 flex-1 min-h-0">
                          <div className={`bg-slate-900/50 rounded-lg p-2 border ${hasError ? "border-red-500/20 bg-red-500/5" : "border-slate-800"}`}>
                            <div className="flex items-center justify-between mb-1">
                              <div className="flex items-center gap-1.5">
                                <div className={`w-1.5 h-1.5 rounded-full ${agent.analyzing ? "bg-blue-400 animate-pulse" : hasError ? "bg-red-400" : "bg-slate-600"}`} />
                                <span className={`text-[9px] uppercase font-semibold tracking-wider ${hasError ? "text-red-400" : "text-blue-400"}`}>{hasError ? "错误" : "AI分析"}</span>
                              </div>
                              {analysisCache.current[`${agent.id}-${currentSymbol}`] && !agent.analyzing && !hasError && (
                                <span className="text-[8px] text-slate-500">已缓存</span>
                              )}
                            </div>
                            <div className="prose prose-invert prose-sm max-w-none h-[320px] overflow-y-auto custom-scrollbar">
                              <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
                                h1: ({ children }) => <h1 className="text-sm font-bold text-slate-100 mb-1">{children}</h1>,
                                h2: ({ children }) => <h2 className="text-xs font-semibold text-slate-200 mb-1 mt-2">{children}</h2>,
                                h3: ({ children }) => <h3 className="text-[11px] font-semibold text-slate-300 mb-0.5 mt-1">{children}</h3>,
                                p:  ({ children }) => <div className="text-[10px] text-slate-300 leading-relaxed mb-1">{children}</div>,
                                ul: ({ children }) => <ul className="list-disc list-inside text-[10px] text-slate-300 mb-1 space-y-0">{children}</ul>,
                                ol: ({ children }) => <ol className="list-decimal list-inside text-[10px] text-slate-300 mb-1 space-y-0">{children}</ol>,
                                li: ({ children }) => <li className="text-[10px] text-slate-300">{children}</li>,
                                strong: ({ children }) => <strong className="text-slate-100 font-semibold">{children}</strong>,
                                code: ({ children }) => <code className="bg-slate-800 text-slate-200 px-0.5 rounded text-[9px] font-mono">{children}</code>,
                              }}>
                                {agent.outputContent || agent.logs}
                              </ReactMarkdown>
                            </div>
                          </div>
                        </div>

                        <div className="px-3 pb-3 flex justify-between items-center gap-1">
                          <Button
                            variant="outline" size="sm"
                            className={`h-7 text-[10px] px-2 border-slate-700 ${canAnalyze ? `${s.text} ${s.border} hover:bg-slate-800` : "text-slate-600 border-slate-700 cursor-not-allowed"}`}
                            disabled={!canAnalyze}
                            onClick={() => { const a = agents.find(x => x.id === agent.id); if (a) fetchAgentAnalysis(a, false); }}
                          >
                            {agent.analyzing ? <><RefreshCw className="w-3 h-3 mr-0.5 animate-spin" />分析中</>
                              : remaining > 0 ? <><RefreshCw className="w-3 h-3 mr-0.5" />{remaining}s</>
                              : isOllamaOffline ? <><WifiOff className="w-3 h-3 mr-0.5" />离线</>
                              : <><Zap className="w-3 h-3 mr-0.5" />分析</>}
                          </Button>
                          <div className="flex gap-1">
                            <Button variant="ghost" size="sm" className="h-7 text-[10px] text-slate-400 hover:text-slate-100 px-2" onClick={() => toggleAgentStatus(agent.id)}>
                              {agent.status === "运行中" ? "暂停" : "启动"}
                            </Button>
                            <Button variant="ghost" size="sm" className={`h-7 text-[10px] px-2 ${configuringAgent === agent.id ? `${s.text} ${s.bg}` : "text-slate-400 hover:text-slate-100"}`}
                              onClick={() => setConfiguringAgent(configuringAgent === agent.id ? null : agent.id)}>
                              <Settings className="w-3 h-3" />
                            </Button>
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </CardContent>
          </Card>
        </div>
      </main>

      {/* ── Order Panel Modal ── */}
      {showOrderPanel && (
        <OrderPanel
          symbol={currentSymbol}
          currentPrice={ticker?.price ?? null}
          onClose={() => setShowOrderPanel(false)}
          onOrderPlaced={() => { fetchPositions(); fetchBalance(); setShowOrderPanel(false); }}
        />
      )}
    </div>
  );
}
