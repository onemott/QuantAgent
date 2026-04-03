"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  BookOpen, BarChart2, TrendingUp, Activity, Brain, Terminal,
  LayoutDashboard, RefreshCw, Play, ChevronRight, Zap,
  BarChart3, AlertTriangle, CheckCircle2, Trophy, Clock, Info, Settings2, History, Sparkles
} from "lucide-react";
import { ScatterChart, Scatter, XAxis, YAxis, ZAxis, Tooltip, ResponsiveContainer, Cell, CartesianGrid } from 'recharts';

// ─── Types ────────────────────────────────────────────────────────────────────
interface StrategyTemplate {
  id: string;
  name: string;
  description: string;
  params: {
    key: string;
    label: string;
    type: "int" | "float";
    default: number;
    min: number;
    max: number;
    step?: number;
  }[];
}

interface OptimizeResult {
  strategy_type: string;
  symbol: string;
  interval: string;
  best_params: Record<string, number>;
  best_sharpe: number;
  best_return: number;
  total_combos: number;
  results: { params: Record<string, number>; sharpe: number; total_return: number }[];
}

interface BatchResult {
  symbol: string;
  strategy_type: string;
  total_return: number;
  annual_return: number;
  sharpe_ratio: number;
  max_drawdown: number;
  win_rate: number;
  total_trades: number;
}

interface OptimizeHistory {
  id: number;
  strategy_type: string;
  symbol: string;
  interval: string;
  best_params: Record<string, number>;
  best_sharpe: number;
  best_return: number;
  total_combos: number;
  created_at: string;
}

// ─── Constants ────────────────────────────────────────────────────────────────
const SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"];
const INTERVALS = ["1h", "4h", "1d"];
const STRATEGY_COLORS: Record<string, string> = {
  ma: "text-blue-400 bg-blue-500/10 border-blue-500/20",
  rsi: "text-purple-400 bg-purple-500/10 border-purple-500/20",
  boll: "text-cyan-400 bg-cyan-500/10 border-cyan-500/20",
  macd: "text-green-400 bg-green-500/10 border-green-500/20",
  ema_triple: "text-orange-400 bg-orange-500/10 border-orange-500/20",
  atr_trend: "text-red-400 bg-red-500/10 border-red-500/20",
};

// ─── Helpers ──────────────────────────────────────────────────────────────────
function fmt(v: number | null | undefined, digits = 2): string {
  if (v == null || isNaN(v)) return "—";
  return v.toFixed(digits);
}
function pct(v: number | null | undefined): string {
  if (v == null || isNaN(v)) return "—";
  return `${(v * 100).toFixed(2)}%`;
}
function colorReturn(v: number): string {
  return v >= 0 ? "text-green-400" : "text-red-400";
}

// ─── Parallel Coordinates Component ───
const ParallelCoordinatesChart = ({ results, paramKeys }: { results: OptimizeResult['results'], paramKeys: string[] }) => {
  // 1. Normalize data
  // Find min/max for each param
  const bounds: Record<string, { min: number, max: number }> = {};
  paramKeys.forEach(key => {
    const values = results.map(r => r.params[key]);
    bounds[key] = { min: Math.min(...values), max: Math.max(...values) };
  });

  // Normalize Sharpe for color
  const sharpes = results.map(r => r.sharpe);
  const minSharpe = Math.min(...sharpes);
  const maxSharpe = Math.max(...sharpes);

  // Layout
  const width = 800;
  const height = 300;
  const padding = { top: 30, right: 50, bottom: 30, left: 50 };
  const graphWidth = width - padding.left - padding.right;
  const graphHeight = height - padding.top - padding.bottom;
  
  const xStep = graphWidth / (paramKeys.length - 1);

  // Helper to get Y coordinate for a value on an axis
  const getY = (key: string, value: number) => {
    const { min, max } = bounds[key];
    if (max === min) return graphHeight / 2;
    // Normalize to 0-1, then scale to height (inverted because SVG y=0 is top)
    const norm = (value - min) / (max - min);
    return graphHeight - (norm * graphHeight);
  };

  // Helper to get color
  const getColor = (sharpe: number) => {
     // Normalize sharpe 0-1
     const norm = (sharpe - minSharpe) / (maxSharpe - minSharpe || 1);
     // Yellow scale
     if (norm > 0.8) return "rgba(250, 204, 21, 0.9)"; // Top 20%
     if (norm > 0.5) return "rgba(250, 204, 21, 0.4)";
     return "rgba(148, 163, 184, 0.1)"; // Slate-400 very transparent
  };
  
  // Sort results so high sharpe is drawn last (on top)
  const sortedResults = [...results].sort((a, b) => a.sharpe - b.sharpe);

  return (
    <div className="w-full overflow-x-auto">
        <svg width="100%" height="100%" viewBox={`0 0 ${width} ${height}`} className="min-w-[600px]">
        <g transform={`translate(${padding.left}, ${padding.top})`}>
            {/* Lines */}
            {sortedResults.map((r, i) => {
                const points = paramKeys.map((key, idx) => {
                    const x = idx * xStep;
                    const y = getY(key, r.params[key]);
                    return `${x},${y}`;
                }).join(" ");
                
                return (
                    <polyline 
                        key={i} 
                        points={points} 
                        fill="none" 
                        stroke={getColor(r.sharpe)} 
                        strokeWidth={r.sharpe > maxSharpe * 0.8 ? 2 : 1}
                    />
                );
            })}
            
            {/* Axes */}
            {paramKeys.map((key, idx) => {
                const x = idx * xStep;
                return (
                    <g key={key} transform={`translate(${x}, 0)`}>
                        {/* Axis Line */}
                        <line x1={0} y1={0} x2={0} y2={graphHeight} stroke="#475569" strokeWidth={2} />
                        {/* Label */}
                        <text x={0} y={-10} textAnchor="middle" fill="#94a3b8" fontSize="12" fontWeight="bold">{key}</text>
                        {/* Min/Max values */}
                        <text x={0} y={graphHeight + 15} textAnchor="middle" fill="#64748b" fontSize="10">{fmt(bounds[key].min)}</text>
                        <text x={0} y={-25} textAnchor="middle" fill="#64748b" fontSize="10">{fmt(bounds[key].max)}</text>
                    </g>
                );
            })}
        </g>
        </svg>
    </div>
  );
};

// ─── Main Page ────────────────────────────────────────────────────────────────
export default function StrategiesPage() {
  const [templates, setTemplates] = useState<StrategyTemplate[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState<string>("ma");
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [interval, setInterval] = useState("1d");
  const [batchSymbols, setBatchSymbols] = useState<string[]>(["BTCUSDT", "ETHUSDT", "SOLUSDT"]);

  // Optimize state
  const [optimizing, setOptimizing] = useState(false);
  const [optimizeResult, setOptimizeResult] = useState<OptimizeResult | null>(null);
  const [optimizeError, setOptimizeError] = useState<string | null>(null);
  const [savingPreset, setSavingPreset] = useState(false);  // 保存预设状态
  const [presetSaved, setPresetSaved] = useState(false);    // 预设保存成功提示
  
  // Algorithm Config
  const [algorithm, setAlgorithm] = useState<"grid" | "optuna">("grid");
  const [nTrials, setNTrials] = useState(50);
  
  // Param config state: { [key]: { start: 10, end: 50, step: 5 } }
  const [paramConfig, setParamConfig] = useState<Record<string, { start: number; end: number; step: number }>>({});

  // Batch backtest state
  const [batching, setBatching] = useState(false);
  const [batchResults, setBatchResults] = useState<BatchResult[]>([]);
  const [batchError, setBatchError] = useState<string | null>(null);

  // History state
  const [history, setHistory] = useState<OptimizeHistory[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);

  // Active tab
  const [tab, setTab] = useState<"optimize" | "batch" | "history">("optimize");

  // Fetch templates
  useEffect(() => {
    fetch("/api/v1/strategy/templates")
      .then(r => r.json())
      .then(data => {
        if (Array.isArray(data)) setTemplates(data);
        else if (Array.isArray(data?.templates)) setTemplates(data.templates);
      })
      .catch(() => {});
  }, []);

  const currentTemplate = templates.find(t => t.id === selectedTemplate);

  // Initialize param config when template changes
  useEffect(() => {
    if (currentTemplate) {
      const initialConfig: Record<string, any> = {};
      currentTemplate.params.forEach(p => {
        // Default step logic
        let step = p.step || (p.type === 'int' ? 1 : 0.1);
        if (p.key.includes('period')) step = 5; // Smarter default for periods
        
        initialConfig[p.key] = {
            start: p.default, 
            end: p.max, 
            step: step
        };
      });
      setParamConfig(initialConfig);
    }
  }, [currentTemplate]);

  // Fetch optimize history
  const fetchHistory = useCallback(async () => {
    setLoadingHistory(true);
    try {
      const res = await fetch(`/api/v1/strategy/optimize/history?limit=20`);
      const data = await res.json();
      if (Array.isArray(data?.history)) setHistory(data.history);
      else if (Array.isArray(data)) setHistory(data);
    } catch {
      // silent
    } finally {
      setLoadingHistory(false);
    }
  }, []);

  // Fetch templates (exposed for refresh after saving preset)
  const fetchTemplates = useCallback(() => {
    fetch("/api/v1/strategy/templates")
      .then(r => r.json())
      .then(data => {
        if (Array.isArray(data)) setTemplates(data);
        else if (Array.isArray(data?.templates)) setTemplates(data.templates);
      })
      .catch(() => {});
  }, []);

  // Save optimized params as preset
  const handleSavePreset = async () => {
    if (!optimizeResult || !selectedTemplate) return;
    
    setSavingPreset(true);
    setPresetSaved(false);
    try {
      const res = await fetch(`/api/v1/strategy/templates/${selectedTemplate}/params`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          params: optimizeResult.best_params,
          updated_by: "optimization"
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "保存失败");
      
      // Success feedback
      setPresetSaved(true);
      // Refresh templates to reflect new defaults
      fetchTemplates();
      // Auto-hide success message after 3s
      setTimeout(() => setPresetSaved(false), 3000);
    } catch (e) {
      setOptimizeError(e instanceof Error ? e.message : "未知错误");
    } finally {
      setSavingPreset(false);
    }
  };

  useEffect(() => {
    if (tab === "history") fetchHistory();
  }, [tab, fetchHistory]);

  const generateRange = (start: number, end: number, step: number, type: 'int' | 'float') => {
      const res = [];
      if (step <= 0) return [start];
      // Limit iterations to prevent browser freeze
      let count = 0;
      for (let v = start; v <= end + (step * 0.001); v += step) {
          res.push(type === 'int' ? Math.round(v) : parseFloat(v.toFixed(4)));
          count++;
          if (count > 200) break; 
      }
      return res;
  };

  const calculateTotalCombos = useMemo(() => {
      if (!currentTemplate) return 0;
      if (algorithm === 'optuna') return nTrials;
      
      let total = 1;
      currentTemplate.params.forEach(p => {
          const cfg = paramConfig[p.key];
          if (cfg) {
              const count = Math.floor((cfg.end - cfg.start) / cfg.step) + 1;
              total *= Math.max(1, count);
          }
      });
      return total;
  }, [currentTemplate, paramConfig, algorithm, nTrials]);

  const handleOptimize = async () => {
    setOptimizing(true);
    setOptimizeResult(null);
    setOptimizeError(null);
    
    try {
      const body: any = {
          strategy_type: selectedTemplate,
          symbol,
          interval,
          limit: 500,
          algorithm,
      };
      
      if (algorithm === 'grid') {
          if (calculateTotalCombos > 2000) {
              throw new Error(`参数组合过多 (${calculateTotalCombos})，请减少范围或增大步长 (建议 < 1000)`);
          }
          
          const ranges: Record<string, number[]> = {};
          currentTemplate?.params.forEach(p => {
              const cfg = paramConfig[p.key];
              if (cfg) {
                  ranges[p.key] = generateRange(cfg.start, cfg.end, cfg.step, p.type);
              }
          });
          body.param_ranges = ranges;
          body.max_combos = 2500;
      } else {
          body.n_trials = nTrials;
      }

      const res = await fetch("/api/v1/strategy/optimize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "优化失败");
      setOptimizeResult(data);
    } catch (e: unknown) {
      setOptimizeError(e instanceof Error ? e.message : "未知错误");
    } finally {
      setOptimizing(false);
    }
  };

  const handleBatch = async () => {
    setBatching(true);
    setBatchResults([]);
    setBatchError(null);
    try {
      const res = await fetch("/api/v1/strategy/backtest/batch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          strategy_type: selectedTemplate,
          symbols: batchSymbols,
          interval,
          limit: 300,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "批量回测失败");
      if (Array.isArray(data.results)) setBatchResults(data.results);
    } catch (e: unknown) {
      setBatchError(e instanceof Error ? e.message : "未知错误");
    } finally {
      setBatching(false);
    }
  };

  const strategyColorCls = STRATEGY_COLORS[selectedTemplate] || "text-slate-400 bg-slate-800 border-slate-700";

  return (
    <div className="min-h-screen bg-[#0a0e1a] text-slate-100">
      {/* ── Header ── */}
      <header className="sticky top-0 z-40 border-b border-slate-800/60 bg-[#0a0e1a]/95 backdrop-blur-md">
        <div className="container mx-auto px-4 h-14 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-orange-500 to-amber-600 flex items-center justify-center shadow-lg shadow-orange-500/20">
              <BookOpen className="w-4 h-4 text-white" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-slate-100">QuantAgent OS</h1>
              <p className="text-[10px] text-slate-400">策略库 & 参数优化</p>
            </div>
          </div>

          <nav className="hidden md:flex items-center gap-1">
            <Link href="/dashboard" className="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-100 hover:bg-slate-800 rounded-lg transition-all flex items-center gap-1.5">
              <LayoutDashboard className="w-4 h-4" /> 仪表盘
            </Link>
            <Link href="/backtest" className="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-100 hover:bg-slate-800 rounded-lg transition-all flex items-center gap-1.5">
              <BarChart2 className="w-4 h-4" /> 回测
            </Link>
            <Link href="/replay" className="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-100 hover:bg-slate-800 rounded-lg transition-all flex items-center gap-1.5">
              <History className="w-4 h-4" /> 历史回放
            </Link>
            <span className="px-3 py-1.5 text-sm text-orange-400 bg-orange-500/10 rounded-lg border border-orange-500/20 font-medium flex items-center gap-1.5">
              <BookOpen className="w-4 h-4" /> 策略库
            </span>
            <Link href="/terminal" className="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-100 hover:bg-slate-800 rounded-lg transition-all flex items-center gap-1.5">
              <Terminal className="w-4 h-4" /> 终端
            </Link>
          </nav>
        </div>
      </header>

      <main className="container mx-auto px-4 py-6 space-y-6">
        {/* ── Strategy Selection Row ── */}
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
          <Card className="bg-slate-900 border-slate-700/50 lg:col-span-1">
            <CardHeader className="pb-3">
              <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
                <div className="w-6 h-6 bg-orange-500/10 rounded flex items-center justify-center border border-orange-500/20">
                  <Activity className="w-3.5 h-3.5 text-orange-400" />
                </div>
                策略选择
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="space-y-1.5">
                {(templates.length > 0 ? templates : [
                  { id: "ma", name: "双均线 (MA)" },
                  { id: "rsi", name: "RSI 振荡器" },
                  { id: "boll", name: "布林带 (BOLL)" },
                  { id: "macd", name: "MACD 信号" },
                  { id: "ema_triple", name: "EMA 三线" },
                  { id: "atr_trend", name: "ATR 趋势止损" },
                ] as { id: string; name: string }[]).map(t => (
                  <button
                    key={t.id}
                    onClick={() => setSelectedTemplate(t.id)}
                    className={`w-full text-left px-3 py-2.5 rounded-lg border text-sm transition-all ${
                      selectedTemplate === t.id
                        ? `${STRATEGY_COLORS[t.id] || "text-slate-100 bg-slate-700 border-slate-600"} font-medium`
                        : "text-slate-400 hover:text-slate-100 hover:bg-slate-800 border-transparent"
                    }`}
                  >
                    {t.name}
                  </button>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Strategy Detail Card */}
          <Card className="bg-slate-900 border-slate-700/50 lg:col-span-3">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
                  <div className={`w-6 h-6 rounded flex items-center justify-center border ${strategyColorCls}`}>
                    <BarChart3 className="w-3.5 h-3.5" />
                  </div>
                  {currentTemplate?.name || selectedTemplate.toUpperCase()}
                </CardTitle>
                <Badge variant="outline" className={`text-xs ${strategyColorCls}`}>
                  {selectedTemplate}
                </Badge>
              </div>
            </CardHeader>
            <CardContent>
              {currentTemplate ? (
                <div className="space-y-4">
                  <p className="text-slate-400 text-sm">{currentTemplate.description}</p>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                    {currentTemplate.params.map(p => (
                      <div key={p.key} className="bg-slate-800/60 rounded-lg px-3 py-2 border border-slate-700/50">
                        <p className="text-slate-400 text-xs mb-0.5">{p.label}</p>
                        <p className="text-slate-100 text-sm font-mono font-bold">{p.default}</p>
                        <p className="text-slate-500 text-[10px]">Min: {p.min}, Max: {p.max}</p>
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <p className="text-slate-500 text-sm">加载策略参数中...</p>
              )}
            </CardContent>
          </Card>
        </div>

        {/* ── Tabs ── */}
        <div className="flex gap-1 bg-slate-800/50 rounded-xl p-1 border border-slate-700/50 w-fit">
          {(["optimize", "batch", "history"] as const).map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
                tab === t
                  ? "bg-slate-700 text-slate-100 shadow"
                  : "text-slate-400 hover:text-slate-100"
              }`}
            >
              {t === "optimize" ? "参数优化" : t === "batch" ? "批量回测" : "优化历史"}
            </button>
          ))}
        </div>

        {/* ── Optimize Tab ── */}
        {tab === "optimize" && (
          <div className="space-y-4">
            <Card className="bg-slate-900 border-slate-700/50">
              <CardHeader className="pb-3 border-b border-slate-800/50">
                <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
                  <Settings2 className="w-4 h-4 text-yellow-400" /> 优化配置
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-6 pt-4">
                {/* 1. Global Settings */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <div className="space-y-1.5">
                    <label className="text-slate-400 text-xs">交易对</label>
                    <Select value={symbol} onValueChange={setSymbol}>
                      <SelectTrigger className="bg-slate-800 border-slate-700 text-slate-100 h-9 text-sm">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent className="bg-slate-800 border-slate-700">
                        {SYMBOLS.map(s => (
                          <SelectItem key={s} value={s} className="text-slate-100 focus:bg-slate-700">{s}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-slate-400 text-xs">K 线周期</label>
                    <Select value={interval} onValueChange={setInterval}>
                      <SelectTrigger className="bg-slate-800 border-slate-700 text-slate-100 h-9 text-sm">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent className="bg-slate-800 border-slate-700">
                        {INTERVALS.map(i => (
                          <SelectItem key={i} value={i} className="text-slate-100 focus:bg-slate-700">{i}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-slate-400 text-xs">优化算法</label>
                    <Select value={algorithm} onValueChange={(v: any) => setAlgorithm(v)}>
                      <SelectTrigger className="bg-slate-800 border-slate-700 text-slate-100 h-9 text-sm">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent className="bg-slate-800 border-slate-700">
                        <SelectItem value="grid" className="text-slate-100 focus:bg-slate-700">网格搜索 (Grid Search)</SelectItem>
                        <SelectItem value="optuna" className="text-slate-100 focus:bg-slate-700">贝叶斯优化 (Optuna)</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>

                {/* 2. Parameter Ranges */}
                <div className="space-y-3 pt-2 border-t border-slate-800/50">
                   <div className="flex items-center justify-between">
                       <h3 className="text-slate-300 text-xs font-medium">参数范围配置</h3>
                       <Badge variant="outline" className="text-xs border-slate-700 text-slate-400">
                           {algorithm === 'grid' ? `预计组合数: ${calculateTotalCombos}` : `最大尝试次数: ${nTrials}`}
                       </Badge>
                   </div>
                   
                   {algorithm === 'grid' ? (
                       <div className="grid grid-cols-1 gap-3">
                           {currentTemplate?.params.map(p => (
                               <div key={p.key} className="flex items-center gap-3 bg-slate-800/30 p-2 rounded-lg border border-slate-700/30">
                                   <div className="w-24 text-xs text-slate-300 font-medium">{p.label}</div>
                                   <div className="flex items-center gap-2 flex-1">
                                       <div className="flex-1 flex items-center gap-2">
                                           <span className="text-[10px] text-slate-500">Start</span>
                                           <input 
                                               type="number" 
                                               className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200"
                                               value={paramConfig[p.key]?.start ?? p.default}
                                               onChange={e => setParamConfig(prev => ({
                                                   ...prev,
                                                   [p.key]: { ...prev[p.key], start: parseFloat(e.target.value) }
                                               }))}
                                           />
                                       </div>
                                       <div className="flex-1 flex items-center gap-2">
                                           <span className="text-[10px] text-slate-500">End</span>
                                           <input 
                                               type="number" 
                                               className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200"
                                               value={paramConfig[p.key]?.end ?? p.max}
                                               onChange={e => setParamConfig(prev => ({
                                                   ...prev,
                                                   [p.key]: { ...prev[p.key], end: parseFloat(e.target.value) }
                                               }))}
                                           />
                                       </div>
                                       <div className="flex-1 flex items-center gap-2">
                                           <span className="text-[10px] text-slate-500">Step</span>
                                           <input 
                                               type="number" 
                                               className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200"
                                               value={paramConfig[p.key]?.step ?? 1}
                                               onChange={e => setParamConfig(prev => ({
                                                   ...prev,
                                                   [p.key]: { ...prev[p.key], step: parseFloat(e.target.value) }
                                               }))}
                                           />
                                       </div>
                                   </div>
                               </div>
                           ))}
                       </div>
                   ) : (
                       <div className="flex items-center gap-4 bg-slate-800/30 p-3 rounded-lg border border-slate-700/30">
                           <div className="text-xs text-slate-400">
                               Optuna 算法将自动在参数定义的 Min/Max 范围内智能搜索最优解。
                           </div>
                           <div className="flex items-center gap-2 ml-auto">
                               <span className="text-xs text-slate-300">尝试次数 (n_trials)</span>
                               <input 
                                   type="number" 
                                   className="w-20 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200"
                                   value={nTrials}
                                   onChange={e => setNTrials(parseInt(e.target.value))}
                               />
                           </div>
                       </div>
                   )}
                </div>

                <div className="pt-2">
                    <Button
                      onClick={handleOptimize}
                      disabled={optimizing}
                      className="w-full h-10 bg-yellow-500 hover:bg-yellow-600 text-slate-900 font-semibold text-sm shadow-lg shadow-yellow-500/10"
                    >
                      {optimizing ? (
                        <><RefreshCw className="w-4 h-4 mr-1.5 animate-spin" /> 正在执行 {algorithm === 'grid' ? '网格搜索' : '智能优化'}...</>
                      ) : (
                        <><Play className="w-4 h-4 mr-1.5" /> 开始优化</>
                      )}
                    </Button>
                </div>

                {optimizeError && (
                  <div className="flex items-center gap-2 text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2 text-sm">
                    <AlertTriangle className="w-4 h-4 flex-shrink-0" /> {optimizeError}
                  </div>
                )}
              </CardContent>
            </Card>

            {optimizeResult && (
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                {/* Best Params */}
                <Card className="bg-slate-900 border-slate-700/50">
                  <CardHeader className="pb-3">
                    <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
                      <Trophy className="w-4 h-4 text-yellow-400" /> 最优参数
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <div className="grid grid-cols-2 gap-2">
                      <div className="bg-slate-800/60 rounded-lg p-2 text-center border border-slate-700/50">
                        <p className="text-slate-400 text-xs">夏普比率</p>
                        <p className="text-yellow-400 text-lg font-bold font-mono">{fmt(optimizeResult.best_sharpe)}</p>
                      </div>
                      <div className="bg-slate-800/60 rounded-lg p-2 text-center border border-slate-700/50">
                        <p className="text-slate-400 text-xs">总收益率</p>
                        <p className={`text-lg font-bold font-mono ${colorReturn(optimizeResult.best_return)}`}>
                          {pct(optimizeResult.best_return)}
                        </p>
                      </div>
                    </div>
                    <div className="space-y-1.5">
                      {Object.entries(optimizeResult.best_params).map(([k, v]) => (
                        <div key={k} className="flex items-center justify-between text-sm">
                          <span className="text-slate-400">{k}</span>
                          <span className="text-slate-100 font-mono font-semibold">{v}</span>
                        </div>
                      ))}
                    </div>
                    <div className="flex items-center gap-1.5 text-slate-500 text-xs">
                      <Info className="w-3 h-3" /> 共测试 {optimizeResult.total_combos} 组参数
                    </div>
                    {presetSaved ? (
                      <div className="flex items-center gap-2 text-green-400 bg-green-500/10 border border-green-500/20 rounded-lg px-3 py-2 text-xs">
                        <CheckCircle2 className="w-4 h-4" /> 预设参数已保存，下次使用自动加载
                      </div>
                    ) : (
                      <Button
                        onClick={handleSavePreset}
                        disabled={savingPreset}
                        size="sm"
                        className="w-full mt-1 h-8 bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-medium"
                      >
                        {savingPreset ? (
                          <><RefreshCw className="w-3 h-3 mr-1.5 animate-spin" /> 保存中...</>
                        ) : (
                          <><Sparkles className="w-3 h-3 mr-1.5" /> 保存为预设参数</>
                        )}
                      </Button>
                    )}
                  </CardContent>
                </Card>

                {/* Heatmap / Scatter Plot (Only for 2 params) */}
                {Object.keys(optimizeResult.best_params).length === 2 && (
                    <Card className="bg-slate-900 border-slate-700/50 lg:col-span-2">
                        <CardHeader className="pb-3">
                            <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
                                <Activity className="w-4 h-4 text-purple-400" /> 参数敏感度分布 (热力图)
                            </CardTitle>
                        </CardHeader>
                        <CardContent className="h-[250px] w-full">
                             <ResponsiveContainer width="100%" height="100%">
                                <ScatterChart margin={{ top: 20, right: 20, bottom: 20, left: 20 }}>
                                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                                  <XAxis 
                                      type="number" 
                                      dataKey={`params.${Object.keys(optimizeResult.best_params)[0]}`} 
                                      name={Object.keys(optimizeResult.best_params)[0]} 
                                      stroke="#94a3b8"
                                      fontSize={12}
                                      tickCount={5}
                                      label={{ value: Object.keys(optimizeResult.best_params)[0], position: 'bottom', fill: '#94a3b8', fontSize: 10 }}
                                      domain={['auto', 'auto']}
                                  />
                                  <YAxis 
                                      type="number" 
                                      dataKey={`params.${Object.keys(optimizeResult.best_params)[1]}`} 
                                      name={Object.keys(optimizeResult.best_params)[1]} 
                                      stroke="#94a3b8"
                                      fontSize={12}
                                      tickCount={5}
                                      label={{ value: Object.keys(optimizeResult.best_params)[1], angle: -90, position: 'left', fill: '#94a3b8', fontSize: 10 }}
                                      domain={['auto', 'auto']}
                                  />
                                  <ZAxis type="number" dataKey="sharpe" range={[50, 400]} name="Sharpe" />
                                  <Tooltip 
                                      cursor={{ strokeDasharray: '3 3' }} 
                                      content={({ payload }) => {
                                          if (payload && payload.length) {
                                              const d = payload[0].payload;
                                              return (
                                                  <div className="bg-slate-800 border border-slate-700 p-2 rounded shadow text-xs">
                                                      <p className="text-slate-300 mb-1">{Object.keys(d.params).map(k => `${k}: ${d.params[k]}`).join(', ')}</p>
                                                      <p className="text-yellow-400 font-mono">Sharpe: {fmt(d.sharpe)}</p>
                                                      <p className={`${colorReturn(d.total_return)} font-mono`}>Return: {pct(d.total_return)}</p>
                                                  </div>
                                              );
                                          }
                                          return null;
                                      }}
                                  />
                                  <Scatter name="Results" data={optimizeResult.results} shape="square">
                                      {optimizeResult.results.map((entry, index) => {
                                          // Color mapping based on Sharpe
                                          // Normalize sharpe between min and max in result set for better contrast
                                          const minSharpe = Math.min(...optimizeResult.results.map(r => r.sharpe));
                                          const maxSharpe = Math.max(...optimizeResult.results.map(r => r.sharpe));
                                          const norm = (entry.sharpe - minSharpe) / (maxSharpe - minSharpe || 1);
                                          
                                          // Heatmap colors: Blue (Low) -> Purple -> Red -> Yellow (High)
                                          let color = "#3b82f6"; // blue
                                          if (norm > 0.25) color = "#8b5cf6"; // purple
                                          if (norm > 0.5) color = "#ef4444"; // red
                                          if (norm > 0.75) color = "#eab308"; // yellow
                                          
                                          return <Cell key={`cell-${index}`} fill={color} fillOpacity={0.8} />;
                                      })}
                                  </Scatter>
                                </ScatterChart>
                             </ResponsiveContainer>
                        </CardContent>
                    </Card>
                )}
                
                {/* Parallel Coordinates (For > 2 params) */}
                {(Object.keys(optimizeResult.best_params).length > 2) && (
                     <Card className="bg-slate-900 border-slate-700/50 lg:col-span-2">
                        <CardHeader className="pb-3">
                            <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
                                <Activity className="w-4 h-4 text-purple-400" /> 多维参数平行坐标图
                            </CardTitle>
                        </CardHeader>
                        <CardContent className="h-[250px] w-full flex items-center justify-center">
                            <ParallelCoordinatesChart 
                                results={optimizeResult.results} 
                                paramKeys={Object.keys(optimizeResult.best_params)} 
                            />
                        </CardContent>
                    </Card>
                )}

                {/* Fallback for < 2 params (Single param) */}
                {(Object.keys(optimizeResult.best_params).length < 2) && (
                     <Card className="bg-slate-900 border-slate-700/50 lg:col-span-2">
                        <CardHeader className="pb-3">
                            <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
                                <Activity className="w-4 h-4 text-purple-400" /> 参数分布
                            </CardTitle>
                        </CardHeader>
                        <CardContent className="flex items-center justify-center h-[200px] w-full">
                            <ResponsiveContainer width="100%" height="100%">
                                <ScatterChart margin={{ top: 20, right: 20, bottom: 20, left: 20 }}>
                                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                                    <XAxis 
                                        type="number" 
                                        dataKey={`params.${Object.keys(optimizeResult.best_params)[0]}`} 
                                        name={Object.keys(optimizeResult.best_params)[0]} 
                                        stroke="#94a3b8" 
                                    />
                                    <YAxis type="number" dataKey="sharpe" name="Sharpe" stroke="#94a3b8" />
                                    <Tooltip contentStyle={{backgroundColor: '#1e293b', borderColor: '#334155'}} />
                                    <Scatter name="Results" data={optimizeResult.results} fill="#eab308" />
                                </ScatterChart>
                            </ResponsiveContainer>
                        </CardContent>
                    </Card>
                )}

                {/* Top Results Table */}
                <Card className="bg-slate-900 border-slate-700/50 lg:col-span-3">
                  <CardHeader className="pb-3">
                    <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
                      <BarChart3 className="w-4 h-4 text-blue-400" /> Top 10 参数组合
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="overflow-x-auto">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="border-b border-slate-700/50">
                            <th className="text-left pb-2 text-slate-400 font-medium">#</th>
                            <th className="text-left pb-2 text-slate-400 font-medium">参数</th>
                            <th className="text-right pb-2 text-slate-400 font-medium">夏普</th>
                            <th className="text-right pb-2 text-slate-400 font-medium">收益率</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-800/50">
                          {(optimizeResult.results || []).slice(0, 10).map((r, idx) => (
                            <tr key={idx} className={idx === 0 ? "bg-yellow-500/5" : ""}>
                              <td className="py-1.5 text-slate-500">{idx + 1}</td>
                              <td className="py-1.5 text-slate-300 font-mono">
                                {Object.values(r.params).join(" / ")}
                              </td>
                              <td className="py-1.5 text-right text-slate-100 font-mono">{fmt(r.sharpe)}</td>
                              <td className={`py-1.5 text-right font-mono ${colorReturn(r.total_return)}`}>
                                {pct(r.total_return)}
                              </td>
                            </tr>
                          ))}
                          {(!optimizeResult.results || optimizeResult.results.length === 0) && (
                            <tr>
                              <td colSpan={4} className="py-4 text-center text-slate-500">
                                暂无详细数据
                              </td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  </CardContent>
                </Card>
              </div>
            )}
          </div>
        )}

        {/* ── Batch Backtest Tab ── */}
        {tab === "batch" && (
          <div className="space-y-4">
            <Card className="bg-slate-900 border-slate-700/50">
              <CardHeader className="pb-3">
                <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
                  <BarChart2 className="w-4 h-4 text-cyan-400" /> 多标的批量回测
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <label className="text-slate-400 text-xs">选择回测标的（可多选）</label>
                  <div className="flex flex-wrap gap-2">
                    {SYMBOLS.map(s => (
                      <button
                        key={s}
                        onClick={() => setBatchSymbols(prev =>
                          prev.includes(s) ? prev.filter(x => x !== s) : [...prev, s]
                        )}
                        className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-all ${
                          batchSymbols.includes(s)
                            ? "text-cyan-400 bg-cyan-500/10 border-cyan-500/30"
                            : "text-slate-400 border-slate-700 hover:border-slate-500"
                        }`}
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <Select value={interval} onValueChange={setInterval}>
                    <SelectTrigger className="w-[120px] bg-slate-800 border-slate-700 text-slate-100 h-9 text-sm">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="bg-slate-800 border-slate-700">
                      {INTERVALS.map(i => (
                        <SelectItem key={i} value={i} className="text-slate-100 focus:bg-slate-700">{i}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Button
                    onClick={handleBatch}
                    disabled={batching || batchSymbols.length === 0}
                    className="h-9 bg-cyan-500 hover:bg-cyan-600 text-slate-900 font-semibold text-sm"
                  >
                    {batching ? (
                      <><RefreshCw className="w-4 h-4 mr-1.5 animate-spin" /> 回测中...</>
                    ) : (
                      <><Play className="w-4 h-4 mr-1.5" /> 批量回测 {batchSymbols.length} 个标的</>
                    )}
                  </Button>
                </div>

                {batchError && (
                  <div className="flex items-center gap-2 text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2 text-sm">
                    <AlertTriangle className="w-4 h-4 flex-shrink-0" /> {batchError}
                  </div>
                )}
              </CardContent>
            </Card>

            {batchResults.length > 0 && (
              <Card className="bg-slate-900 border-slate-700/50">
                <CardHeader className="pb-3">
                  <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
                    <Trophy className="w-4 h-4 text-yellow-400" /> 回测排行榜
                    <Badge variant="outline" className="text-xs text-slate-400 border-slate-600 ml-2">
                      {batchResults.length} 个标的
                    </Badge>
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-slate-700/50">
                          <th className="text-left pb-3 text-slate-400 font-medium">#</th>
                          <th className="text-left pb-3 text-slate-400 font-medium">标的</th>
                          <th className="text-right pb-3 text-slate-400 font-medium">总收益</th>
                          <th className="text-right pb-3 text-slate-400 font-medium">年化收益</th>
                          <th className="text-right pb-3 text-slate-400 font-medium">夏普</th>
                          <th className="text-right pb-3 text-slate-400 font-medium">最大回撤</th>
                          <th className="text-right pb-3 text-slate-400 font-medium">胜率</th>
                          <th className="text-right pb-3 text-slate-400 font-medium">交易次数</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800/50">
                        {batchResults.map((r, idx) => (
                          <tr key={r.symbol} className={idx === 0 ? "bg-yellow-500/5" : "hover:bg-slate-800/30"}>
                            <td className="py-2.5 text-slate-500 font-mono">
                              {idx === 0 ? "🥇" : idx === 1 ? "🥈" : idx === 2 ? "🥉" : idx + 1}
                            </td>
                            <td className="py-2.5">
                              <span className="text-slate-100 font-semibold">{r.symbol}</span>
                            </td>
                            <td className={`py-2.5 text-right font-mono font-semibold ${colorReturn(r.total_return)}`}>
                              {pct(r.total_return)}
                            </td>
                            <td className={`py-2.5 text-right font-mono ${colorReturn(r.annual_return)}`}>
                              {pct(r.annual_return)}
                            </td>
                            <td className="py-2.5 text-right text-slate-100 font-mono">{fmt(r.sharpe_ratio)}</td>
                            <td className="py-2.5 text-right text-red-400 font-mono">{pct(r.max_drawdown)}</td>
                            <td className="py-2.5 text-right text-blue-400 font-mono">{pct(r.win_rate)}</td>
                            <td className="py-2.5 text-right text-slate-400">{r.total_trades}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>
            )}
          </div>
        )}

        {/* ── History Tab ── */}
        {tab === "history" && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-slate-100 text-sm font-medium">历史优化记录</h2>
              <Button
                variant="outline"
                size="sm"
                onClick={fetchHistory}
                disabled={loadingHistory}
                className="border-slate-700 text-slate-400 hover:text-slate-100 h-8 text-xs"
              >
                <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${loadingHistory ? "animate-spin" : ""}`} />
                刷新
              </Button>
            </div>

            {history.length === 0 && !loadingHistory && (
              <div className="text-center py-12 text-slate-500">
                <BarChart3 className="w-10 h-10 mx-auto mb-3 opacity-30" />
                <p>暂无优化记录，请先执行参数优化</p>
              </div>
            )}

            <div className="space-y-3">
              {history.map(h => (
                <Card key={h.id} className="bg-slate-900 border-slate-700/50 hover:border-slate-600/50 transition-all">
                  <CardContent className="p-4">
                    <div className="flex items-start justify-between">
                      <div className="space-y-1">
                        <div className="flex items-center gap-2">
                          <Badge variant="outline" className={`text-xs ${STRATEGY_COLORS[h.strategy_type] || "text-slate-400 border-slate-600"}`}>
                            {h.strategy_type}
                          </Badge>
                          <span className="text-slate-100 font-semibold text-sm">{h.symbol}</span>
                          <span className="text-slate-500 text-xs">{h.interval}</span>
                        </div>
                        <div className="flex items-center gap-4 text-xs">
                          <span className="text-slate-400">最优参数：
                            <span className="text-slate-200 font-mono ml-1">
                              {Object.entries(h.best_params).map(([k, v]) => `${k}=${v}`).join(", ")}
                            </span>
                          </span>
                        </div>
                      </div>
                      <div className="text-right space-y-1">
                        <div className="flex items-center gap-3 text-sm">
                          <div>
                            <p className="text-slate-500 text-xs">夏普</p>
                            <p className="text-yellow-400 font-mono font-bold">{fmt(h.best_sharpe)}</p>
                          </div>
                          <div>
                            <p className="text-slate-500 text-xs">收益率</p>
                            <p className={`font-mono font-bold ${colorReturn(h.best_return)}`}>{pct(h.best_return)}</p>
                          </div>
                          <div>
                            <p className="text-slate-500 text-xs">测试组数</p>
                            <p className="text-slate-300 font-mono">{h.total_combos}</p>
                          </div>
                        </div>
                        <div className="flex items-center gap-1 text-slate-500 text-xs justify-end">
                          <Clock className="w-3 h-3" />
                          {new Date(h.created_at).toLocaleString("zh-CN")}
                        </div>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
