"use client";

import { useState, useRef, useCallback, useEffect, useMemo } from "react";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  Brain, Send, RefreshCw, BarChart3, BarChart, Activity,
  TrendingUp, Shield, Zap, ChevronDown, ChevronUp, X, Clock,
  AlertTriangle, CheckCircle, Info, BookOpen, LayoutDashboard, WifiOff, Cpu,
  History
} from "lucide-react";

// ── Types ────────────────────────────────────────────────────────────────────

type MessageRole = "user" | "system" | "agent";

interface TimelineStep {
  id:        string;
  agentName: string;
  agentId:   string;
  status:    "pending" | "running" | "done" | "error";
  signal?:   string;
  confidence?: number;
  content:   string;
  startTime: number;
  endTime?:  number;
}

interface FinalDecision {
  symbol:         string;
  final_signal:   string;
  confidence:     number;
  summary:        string;
  vote_breakdown: { bullish: number; bearish: number; neutral: number };
  risk_veto:      boolean;
}

interface ConversationMessage {
  id:      string;
  role:    MessageRole;
  content: string;
  ts:      number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const AGENT_INFO: Record<string, { name: string; icon: any; color: string }> = {
  trend:         { name: "趋势跟踪 Agent", icon: TrendingUp, color: "blue" },
  mean_reversion:{ name: "均值回归 Agent", icon: Activity,   color: "purple" },
  risk:          { name: "风险管理 Agent", icon: Shield,      color: "orange" },
};

const LLM_PROVIDERS = [
  { value: "openai",     label: "Custom Model (Aliyun Qwen)" },
  { value: "ollama",    label: "Ollama (Local)" },
  { value: "openrouter",label: "OpenRouter" },
];

const SYMBOLS = [
  { value: "BTCUSDT", label: "BTC/USDT" },
  { value: "ETHUSDT", label: "ETH/USDT" },
  { value: "SOLUSDT", label: "SOL/USDT" },
  { value: "BNBUSDT", label: "BNB/USDT" },
  { value: "XRPUSDT", label: "XRP/USDT" },
  { value: "DOGEUSDT", label: "DOGE/USDT" },
];

const SIGNAL_COLORS: Record<string, string> = {
  BUY:           "text-green-400 bg-green-500/10 border-green-500/20",
  SELL:          "text-red-400 bg-red-500/10 border-red-500/20",
  WAIT:          "text-yellow-400 bg-yellow-500/10 border-yellow-500/20",
  HOLD:          "text-blue-400 bg-blue-500/10 border-blue-500/20",
  LONG_REVERSAL: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20",
  SHORT_REVERSAL:"text-rose-400 bg-rose-500/10 border-rose-500/20",
};

// Hydration-safe time formatter - returns consistent placeholder during SSR
function formatTime(ts: number): string {
  const date = new Date(ts);
  const hours = date.getHours().toString().padStart(2, "0");
  const minutes = date.getMinutes().toString().padStart(2, "0");
  return `${hours}:${minutes}`;
}

// ── Sub-components ────────────────────────────────────────────────────────────

function TimelineCard({ step }: { step: TimelineStep }) {
  const [expanded, setExpanded] = useState(false);
  const info = AGENT_INFO[step.agentId] || { name: step.agentName, icon: Brain, color: "gray" };
  const Icon = info.icon;
  const elapsed = step.endTime ? ((step.endTime - step.startTime) / 1000).toFixed(1) : null;

  return (
    <div className={`rounded-xl border transition-all ${
      step.status === "error" ? "border-red-500/30 bg-red-500/5" :
      step.status === "done"  ? "border-slate-700/50 bg-slate-800/40" :
      step.status === "running" ? "border-blue-500/30 bg-blue-500/5" :
      "border-slate-700/30 bg-slate-900/40"
    }`}>
      <div
        className="flex items-center gap-3 p-3 cursor-pointer select-none"
        onClick={() => step.content && setExpanded(e => !e)}
      >
        <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${
          info.color === "blue"   ? "bg-blue-500/10 border border-blue-500/20" :
          info.color === "purple" ? "bg-purple-500/10 border border-purple-500/20" :
          info.color === "orange" ? "bg-orange-500/10 border border-orange-500/20" :
          "bg-slate-700/50 border border-slate-600/30"
        }`}>
          {step.status === "running"
            ? <RefreshCw className="w-4 h-4 animate-spin text-blue-400" />
            : step.status === "error"
              ? <AlertTriangle className={`w-4 h-4 text-red-400`} />
              : step.status === "done"
                ? <CheckCircle className="w-4 h-4 text-green-400" />
                : <Icon className={`w-4 h-4 ${
                    info.color === "blue" ? "text-blue-400" :
                    info.color === "purple" ? "text-purple-400" : "text-orange-400"
                  }`} />
          }
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-slate-100 text-sm font-semibold">{info.name}</span>
            {step.status === "running" && (
              <span className="text-[10px] text-blue-400 animate-pulse">分析中...</span>
            )}
          </div>
          {step.signal && (
            <div className="flex items-center gap-2 mt-0.5">
              <span className={`text-[10px] px-1.5 py-0.5 rounded border font-semibold ${SIGNAL_COLORS[step.signal] || "text-slate-400"}`}>
                {step.signal}
              </span>
              {step.confidence !== undefined && (
                <span className="text-[10px] text-slate-500">置信度: {(step.confidence * 100).toFixed(0)}%</span>
              )}
            </div>
          )}
        </div>

        <div className="flex items-center gap-2">
          {elapsed && <span className="text-[10px] text-slate-500">{elapsed}s</span>}
          {step.content && (
            expanded ? <ChevronUp className="w-3.5 h-3.5 text-slate-400" /> : <ChevronDown className="w-3.5 h-3.5 text-slate-400" />
          )}
        </div>
      </div>

      {expanded && step.content && (
        <div className="px-3 pb-3 border-t border-slate-700/30 mt-0 pt-2">
          <div className="prose prose-invert prose-sm max-w-none max-h-64 overflow-y-auto custom-scrollbar">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
              p:  ({ children }) => <p className="text-[11px] text-slate-300 leading-relaxed mb-1">{children}</p>,
              h2: ({ children }) => <h2 className="text-xs font-bold text-slate-200 mb-1 mt-2">{children}</h2>,
              h3: ({ children }) => <h3 className="text-[11px] font-semibold text-slate-300 mb-0.5 mt-1">{children}</h3>,
              ul: ({ children }) => <ul className="list-disc list-inside text-[11px] text-slate-300 mb-1">{children}</ul>,
              li: ({ children }) => <li className="text-[11px] text-slate-300">{children}</li>,
              strong: ({ children }) => <strong className="text-slate-100 font-bold">{children}</strong>,
              table: ({ children }) => <table className="text-[10px] w-full mb-2 border-collapse">{children}</table>,
              th: ({ children }) => <th className="text-left px-1 py-0.5 text-slate-400 border-b border-slate-700">{children}</th>,
              td: ({ children }) => <td className="px-1 py-0.5 text-slate-300">{children}</td>,
            }}>
              {step.content}
            </ReactMarkdown>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main Terminal Page ─────────────────────────────────────────────────────────

export default function TerminalPage() {
  const [symbol, setSymbol]               = useState("BTCUSDT");
  const [provider, setProvider]           = useState("openai");
  const [ollamaStatus, setOllamaStatus]   = useState<{ online: boolean; checked: boolean }>({ online: false, checked: false });
  const [input, setInput]                 = useState("");
  const [isAnalyzing, setIsAnalyzing]     = useState(false);
  const [timeline, setTimeline]           = useState<TimelineStep[]>([]);
  const [finalDecision, setFinalDecision] = useState<FinalDecision | null>(null);
  const [conversation, setConversation]   = useState<ConversationMessage[]>([]);
  const [mounted, setMounted]             = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  
  // Use ref to track latest timeline for coordinator call
  const timelineRef = useRef<TimelineStep[]>([]);
  useEffect(() => {
    timelineRef.current = timeline;
  }, [timeline]);

  // Hydration fix: use consistent initial timestamp
  useEffect(() => {
    setMounted(true);
  }, []);

  // Check Ollama status on mount
  useEffect(() => {
    fetch("/api/v1/market/ollama/status")
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setOllamaStatus({ ...d, checked: true }); })
      .catch(() => setOllamaStatus({ online: false, checked: true }));
  }, []);

  // Initialize conversation with fixed timestamp to avoid hydration mismatch
  useEffect(() => {
    if (mounted) {
      setConversation([
        { id: "welcome", role: "system", content: "欢迎使用 QuantAgent 自然语言交易终端。\n\n你可以直接输入分析指令，例如：\n- **「分析 BTC 当前趋势」**\n- **「帮我评估 ETH 的风险」**\n- **「对 SOL 做多 Agent 协作分析」**\n\n或者直接点击下方快捷按钮开始分析。", ts: Date.now() },
      ]);
    }
  }, [mounted]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [conversation, timeline, finalDecision]);

  const idCounter = useRef(0);
  const addMessage = useCallback((role: MessageRole, content: string) => {
    idCounter.current += 1;
    setConversation(prev => [...prev, { id: `${Date.now()}-${idCounter.current}`, role, content, ts: Date.now() }]);
  }, []);

  const isOllamaOffline = provider === "ollama" && ollamaStatus.checked && !ollamaStatus.online;

  const runCoordination = useCallback(async (sym: string, providerOverride?: string) => {
    const activeProvider = providerOverride ?? provider;
    if (isAnalyzing) return;
    setIsAnalyzing(true);
    setTimeline([]);
    setFinalDecision(null);

    addMessage("system", `正在启动多 Agent 协作分析: **${sym}**...`);

    const agentOrder = [
      { id: "trend",          name: "趋势跟踪 Agent" },
      { id: "mean_reversion", name: "均值回归 Agent" },
      { id: "risk",           name: "风险管理 Agent" },
    ];

    // Initialize all steps as pending
    setTimeline(agentOrder.map(a => ({
      id:        a.id,
      agentName: a.name,
      agentId:   a.id,
      status:    "pending",
      content:   "",
      startTime: Date.now(),
    })));

    try {
      // Run each agent sequentially for clear progress display
      for (const agentDef of agentOrder) {
        const startTime = Date.now();
        setTimeline(prev => prev.map(s =>
          s.id === agentDef.id ? { ...s, status: "running", startTime } : s
        ));

        try {
          const providerParam = activeProvider && activeProvider !== "default" ? `&provider=${activeProvider}` : "";
          const res = await fetch(
            `/api/v1/market/agent-analysis-stream/${agentDef.id}/${sym}?interval=1h${providerParam}`,
            { headers: { Accept: "text/event-stream" } }
          );
          if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

          const reader  = res.body.getReader();
          const decoder = new TextDecoder();
          let   buf     = "";
          let   content = "";
          let   signal  = "";
          let   confidence = 0;

          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buf += decoder.decode(value, { stream: true });
            const lines = buf.split("\n");
            buf = lines.pop() ?? "";

            for (const line of lines) {
              if (!line.startsWith("data: ")) continue;
              try {
                const p = JSON.parse(line.slice(6).trim());
                if (p.done) {
                  signal     = p.signal || "";
                  confidence = p.confidence || 0;
                  break;
                }
                if (p.chunk) {
                  content += p.chunk;
                  setTimeline(prev => prev.map(s =>
                    s.id === agentDef.id ? { ...s, content } : s
                  ));
                }
              } catch { /* ignore */ }
            }
          }

          setTimeline(prev => prev.map(s =>
            s.id === agentDef.id
              ? { ...s, status: "done", content, signal, confidence, endTime: Date.now() }
              : s
          ));
        } catch (e: any) {
          setTimeline(prev => prev.map(s =>
            s.id === agentDef.id
              ? { ...s, status: "error", content: `分析失败: ${e.message}`, endTime: Date.now() }
              : s
          ));
        }
      }

      // Final coordination — call lightweight coordinator endpoint with collected results
      addMessage("system", "所有 Agent 分析完毕，协调者正在综合决策...");
      try {
        // Prepare agent signals from timeline results
        const agentSignals = timelineRef.current
          .filter(step => step.status === "done" && step.signal)
          .map(step => ({
            agent_id: step.agentId,
            agent_name: step.agentName,
            signal: step.signal!,
            confidence: step.confidence || 0.6,
            reasoning: step.content || "",
          }));

        if (agentSignals.length === 0) {
          addMessage("system", "未收集到有效的 Agent 分析结果，无法生成综合决策");
          return;
        }

        const coordRes = await fetch(`/api/v1/market/coordinate/aggregate`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            symbol: sym,
            interval: "1h",
            agent_signals: agentSignals,
            provider: activeProvider !== "default" ? activeProvider : undefined,
          }),
        });
        
        if (coordRes.ok) {
          const coord: FinalDecision = await coordRes.json();
          setFinalDecision(coord);
          addMessage("agent", coord.summary || `最终信号: **${coord.final_signal}** (置信度: ${(coord.confidence * 100).toFixed(0)}%)`);
        } else {
          const errorText = await coordRes.text();
          console.error("Coordinator error:", errorText);
          addMessage("system", `协调者决策失败: ${coordRes.status} ${coordRes.statusText}`);
        }
      } catch (e: any) {
        console.error("Coordinator fetch error:", e);
        addMessage("system", `协调者调用失败: ${e.message || "网络错误"}`);
      }

  // eslint-disable-next-line react-hooks/exhaustive-deps
    } finally {
      setIsAnalyzing(false);
    }
  }, [isAnalyzing, addMessage, provider]);

  const handleSend = useCallback(() => {
    const text = input.trim();
    if (!text || isAnalyzing) return;
    addMessage("user", text);
    setInput("");

    // Simple intent detection
    const upper = text.toUpperCase();
    const detected = SYMBOLS.find(s => upper.includes(s.value) || upper.includes(s.label.replace("/", "")));
    const targetSym = detected ? detected.value : symbol;
    if (detected) setSymbol(targetSym);
    runCoordination(targetSym);
  }, [input, isAnalyzing, symbol, runCoordination, addMessage]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); }
  };

  return (
    <div className="min-h-screen bg-slate-950 flex flex-col">
      {/* ── Header ── */}
      <header className="border-b border-slate-800 bg-slate-900/50 backdrop-blur-sm sticky top-0 z-40">
        <div className="container mx-auto px-4 py-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 bg-gradient-to-br from-purple-500 to-blue-600 rounded-xl flex items-center justify-center">
                <Brain className="w-5 h-5 text-white" />
              </div>
              <div>
                <h1 className="text-lg font-bold text-slate-100">QuantAgent Terminal</h1>
                <p className="text-[10px] text-slate-400">Multi-Agent Natural Language Trading</p>
              </div>
            </div>

            <nav className="hidden md:flex items-center gap-1">
              <Link href="/dashboard" className="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-100 hover:bg-slate-800 rounded-lg transition-all flex items-center gap-1.5">
                <LayoutDashboard className="w-4 h-4" /> 仪表盘
              </Link>
              <Link href="/backtest" className="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-100 hover:bg-slate-800 rounded-lg transition-all flex items-center gap-1.5">
                <BarChart className="w-4 h-4" /> 回测
              </Link>
              <Link href="/replay" className="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-100 hover:bg-slate-800 rounded-lg transition-all flex items-center gap-1.5">
                <History className="w-4 h-4" /> 历史回放
              </Link>
              <Link href="/strategies" className="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-100 hover:bg-slate-800 rounded-lg transition-all flex items-center gap-1.5">
                <BookOpen className="w-4 h-4" /> 策略库
              </Link>
              <span className="px-3 py-1.5 text-sm text-purple-400 bg-purple-500/10 rounded-lg border border-purple-500/20 font-medium flex items-center gap-1.5">
                <Brain className="w-4 h-4" /> 终端
              </span>
            </nav>

            <div className="flex items-center gap-2">
              {/* LLM Provider Selector */}
              <div className="flex flex-col items-end gap-0.5">
                <div className="flex items-center gap-1.5">
                  <Cpu className="w-3.5 h-3.5 text-slate-400" />
                  <Select value={provider} onValueChange={v => { setProvider(v); if (v === "ollama") fetch("/api/v1/market/ollama/status").then(r => r.ok ? r.json() : null).then(d => { if (d) setOllamaStatus({ ...d, checked: true }); }).catch(() => setOllamaStatus({ online: false, checked: true })); }}>
                    <SelectTrigger className={`w-[185px] bg-slate-800 border-slate-700 text-slate-100 h-8 text-sm ${isOllamaOffline ? "border-orange-500/50" : ""}`}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="bg-slate-800 border-slate-700">
                      {LLM_PROVIDERS.map(p => (
                        <SelectItem key={p.value} value={p.value} className="text-slate-100 focus:bg-slate-700 cursor-pointer">{p.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                {provider === "ollama" && ollamaStatus.checked && (
                  <span className={`text-[10px] ${ollamaStatus.online ? "text-green-400" : "text-orange-400"} flex items-center gap-0.5`}>
                    {ollamaStatus.online ? <><CheckCircle className="w-2.5 h-2.5" />在线</> : <><WifiOff className="w-2.5 h-2.5" />未运行</>}
                  </span>
                )}
              </div>
              {/* Symbol Selector */}
              <Select value={symbol} onValueChange={setSymbol}>
                <SelectTrigger className="w-[130px] bg-slate-800 border-slate-700 text-slate-100 h-8 text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-slate-800 border-slate-700">
                  {SYMBOLS.map(s => (
                    <SelectItem key={s.value} value={s.value} className="text-slate-100 focus:bg-slate-700 cursor-pointer">{s.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        </div>
      </header>

      {/* ── Main ── */}
      <main className="flex-1 container mx-auto px-4 py-4 flex gap-4 min-h-0">

        {/* Left: Conversation + Input */}
        <div className="flex-1 flex flex-col gap-3 min-w-0">
          {/* Conversation history */}
          <Card className="flex-1 bg-gradient-to-br from-slate-900 to-slate-800/30 border-slate-700/50 overflow-hidden">
            <CardHeader className="py-3 px-4 border-b border-slate-700/30">
              <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
                <Info className="w-4 h-4 text-blue-400" /> 对话记录
              </CardTitle>
            </CardHeader>
            <CardContent className="p-4 overflow-y-auto max-h-[60vh] custom-scrollbar space-y-3">
              {!mounted ? (
                <div className="flex items-center justify-center py-12 text-slate-500">
                  <RefreshCw className="w-6 h-6 animate-spin" />
                </div>
              ) : (
                conversation.map(msg => (
                  <div key={msg.id} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                    <div className={`max-w-[85%] rounded-xl px-4 py-2.5 ${
                      msg.role === "user"
                        ? "bg-blue-600 text-white"
                        : msg.role === "agent"
                          ? "bg-purple-500/10 border border-purple-500/20 text-slate-100"
                          : "bg-slate-800/60 border border-slate-700/30 text-slate-300"
                    }`}>
                      <div className="prose prose-invert prose-sm max-w-none">
                        <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
                          p: ({ children }) => <p className="text-[12px] leading-relaxed m-0">{children}</p>,
                          strong: ({ children }) => <strong className="font-bold">{children}</strong>,
                          code: ({ children }) => <code className="bg-black/20 px-1 rounded text-[11px]">{children}</code>,
                        }}>
                          {msg.content}
                        </ReactMarkdown>
                      </div>
                      <p className="text-[9px] opacity-40 mt-1 text-right">
                        {formatTime(msg.ts)}
                      </p>
                    </div>
                  </div>
                ))
              )}

              <div ref={bottomRef} />
            </CardContent>
          </Card>

          {/* Quick action chips */}
          {isOllamaOffline && (
            <div className="p-2.5 bg-orange-500/10 border border-orange-500/30 rounded-lg flex items-start gap-2">
              <WifiOff className="w-3.5 h-3.5 text-orange-400 mt-0.5 shrink-0" />
              <div className="text-xs text-orange-300">
                <span className="font-semibold">Ollama 本地服务未运行</span>
                <span className="ml-2 text-orange-400/70">启动命令：<code className="bg-slate-800 px-1 rounded">ollama run qwen3:8b</code></span>
              </div>
            </div>
          )}
          <div className="flex gap-2 flex-wrap">
            {[
              { label: "趋势分析", prompt: `分析 ${symbol} 的价格趋势` },
              { label: "风险评估", prompt: `评估 ${symbol} 当前的风险` },
              { label: "多 Agent 协作", prompt: `对 ${symbol} 进行多智能体协作分析` },
            ].map(chip => (
              <button
                key={chip.label}
                onClick={() => { setInput(chip.prompt); }}
                disabled={isAnalyzing}
                className="px-3 py-1.5 text-xs bg-slate-800 border border-slate-700 text-slate-300 rounded-full hover:bg-slate-700 hover:text-slate-100 transition-all disabled:opacity-40"
              >
                <Zap className="w-3 h-3 inline mr-1" />{chip.label}
              </button>
            ))}
          </div>

          {/* Input box */}
          <div className="flex gap-2">
            <div className="flex-1 relative">
              <textarea
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                disabled={isAnalyzing}
                placeholder={`向 AI Agent 下达分析指令，例如「分析 ${symbol} 当前趋势」...`}
                rows={2}
                className="w-full bg-slate-800 border border-slate-700 rounded-xl px-4 py-3 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-purple-500/50 resize-none disabled:opacity-40"
              />
            </div>
            <Button
              onClick={handleSend}
              disabled={!input.trim() || isAnalyzing}
              className="h-auto bg-purple-600 hover:bg-purple-500 text-white rounded-xl px-4"
            >
              {isAnalyzing
                ? <RefreshCw className="w-4 h-4 animate-spin" />
                : <Send className="w-4 h-4" />}
            </Button>
          </div>
        </div>

        {/* Right: Agent Timeline */}
        <div className="w-[320px] shrink-0 flex flex-col gap-3">
          <Card className="bg-gradient-to-br from-slate-900 to-slate-800/30 border-slate-700/50">
            <CardHeader className="py-3 px-4 border-b border-slate-700/30">
              <div className="flex items-center justify-between">
                <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
                  <Activity className="w-4 h-4 text-purple-400" />
                  Agent 执行时间轴
                </CardTitle>
                {timeline.length > 0 && (
                  <button onClick={() => { setTimeline([]); setFinalDecision(null); }} className="text-slate-500 hover:text-slate-300">
                    <X className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            </CardHeader>
            <CardContent className="p-3 space-y-2 max-h-[70vh] overflow-y-auto custom-scrollbar">
              {timeline.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 text-slate-500">
                  <Brain className="w-10 h-10 mb-3 opacity-20" />
                  <p className="text-xs">Agent 时间轴</p>
                  <p className="text-[10px] text-slate-600 mt-1">发送分析指令后，各 Agent 的决策过程将在此展示</p>
                </div>
              ) : (
                <>
                  {timeline.map(step => (
                    <TimelineCard key={step.id} step={step} />
                  ))}
                  {isAnalyzing && (
                    <div className="flex items-center gap-2 p-2 text-slate-500 text-xs">
                      <RefreshCw className="w-3 h-3 animate-spin" />
                      Agent 分析进行中...
                    </div>
                  )}
                </>
              )}
            </CardContent>
          </Card>

          {/* Coordinator Final Decision Card - Moved to timeline panel */}
          {finalDecision && (
            <Card className={`border ${
              finalDecision.final_signal === "BUY" || finalDecision.final_signal === "LONG_REVERSAL"
                ? "border-green-500/30 bg-green-500/5"
                : finalDecision.final_signal === "SELL" || finalDecision.final_signal === "SHORT_REVERSAL"
                  ? "border-red-500/30 bg-red-500/5"
                  : "border-yellow-500/30 bg-yellow-500/5"
            }`}>
              <CardHeader className="py-3 px-4 border-b border-slate-700/30">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
                    <Brain className="w-4 h-4 text-purple-400" />
                    协调者最终决策
                  </CardTitle>
                  <span className={`text-xs font-bold px-2 py-0.5 rounded border ${SIGNAL_COLORS[finalDecision.final_signal] || ""}`}>
                    {finalDecision.final_signal}
                  </span>
                </div>
              </CardHeader>
              <CardContent className="p-3 space-y-3">
                {finalDecision.risk_veto && (
                  <div className="p-2 rounded-lg bg-orange-500/10 border border-orange-500/20 text-orange-300 text-xs">
                    [!] 风险 Agent 已触发熔断保护
                  </div>
                )}
                <div className="grid grid-cols-3 gap-2">
                  <div className="text-center p-2 bg-green-500/10 rounded-lg">
                    <p className="text-[10px] text-slate-400">看多</p>
                    <p className="text-green-400 font-bold text-sm">{((finalDecision.vote_breakdown?.bullish || 0) * 100).toFixed(0)}%</p>
                  </div>
                  <div className="text-center p-2 bg-red-500/10 rounded-lg">
                    <p className="text-[10px] text-slate-400">看空</p>
                    <p className="text-red-400 font-bold text-sm">{((finalDecision.vote_breakdown?.bearish || 0) * 100).toFixed(0)}%</p>
                  </div>
                  <div className="text-center p-2 bg-slate-700/40 rounded-lg">
                    <p className="text-[10px] text-slate-400">中性</p>
                    <p className="text-slate-400 font-bold text-sm">{((finalDecision.vote_breakdown?.neutral || 0) * 100).toFixed(0)}%</p>
                  </div>
                </div>
                <div className="text-xs text-slate-400">
                  置信度: <span className="text-slate-200 font-semibold">{(finalDecision.confidence * 100).toFixed(0)}%</span>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Quick analyze button */}
          <Button
            onClick={() => runCoordination(symbol)}
            disabled={isAnalyzing || isOllamaOffline}
            className="w-full bg-gradient-to-r from-purple-600 to-blue-600 hover:from-purple-500 hover:to-blue-500 text-white rounded-xl disabled:opacity-50"
          >
            {isAnalyzing
              ? <><RefreshCw className="w-4 h-4 animate-spin mr-2" />分析中...</>
              : isOllamaOffline
                ? <><WifiOff className="w-4 h-4 mr-2" />Ollama 未运行</>
                : <><Zap className="w-4 h-4 mr-2" />启动 {symbol} 多 Agent 分析</>}
          </Button>
        </div>
      </main>
    </div>
  );
}
