"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import Link from "next/link";
import { CompositionCompareChart } from "@/components/charts/CompositionCompareChart";
import { WfeCompareChart } from "@/components/charts/WfeCompareChart";
import { ParamStabilityChart } from "@/components/charts/ParamStabilityChart";
import { EquityCurveChart } from "@/components/charts/EquityCurveChart";
import { MarketConfigPanel } from "@/components/backtest/MarketConfigPanel";
import { createChart, LineSeries, createSeriesMarkers, IChartApi, ISeriesApi, Time } from "lightweight-charts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  BarChart3, TrendingUp, TrendingDown, Activity, RefreshCw,
  Play, ChevronRight, Info, ArrowLeft, Clock, DollarSign,
  BarChart2, Percent, AlertTriangle, CheckCircle2, Terminal, BookOpen, LayoutDashboard,
  HelpCircle, History, Trash2, X, Layers
} from "lucide-react";

// ─── Types ────────────────────────────────────────────────────────────────────
interface ParamDef {
  key: string;
  label: string;
  type: "int" | "float";
  default: number;
  min: number;
  max: number;
  step?: number;
  description?: string;
}

interface Template {
  id: string;
  name: string;
  description: string;
  params: ParamDef[];
}

interface BacktestMetrics {
  total_return: number;
  annual_return: number;
  max_drawdown: number;
  sharpe_ratio: number;
  win_rate: number;
  profit_factor: number;
  total_trades: number;
  total_commission: number;
  initial_capital: number;
  final_capital: number;
}

interface TradeRecord {
  entry_time: string;
  exit_time: string;
  entry_price: number;
  exit_price: number;
  quantity: number;
  pnl: number;
  pnl_pct: number;
}

interface TradeMarker {
  time: string;
  price: number;
  side: "BUY" | "SELL";
  quantity?: number;
  pnl?: number | null;
}

interface BacktestResult {
  id: number | null;
  strategy_type: string;
  symbol: string;
  interval: string;
  params: Record<string, number>;
  metrics: BacktestMetrics;
  equity_curve: { t: string; v: number }[];
  baseline_curve: { t: string; v: number }[];
  markers: TradeMarker[];
  trades: TradeRecord[];
  created_at: string;
}

// ─── Metric Card ──────────────────────────────────────────────────────────────
function MetricCard({ label, value, positive, sub }: { label: string; value: string; positive?: boolean; sub?: string }) {
  return (
    <div className="p-4 bg-slate-800/50 rounded-xl border border-slate-700/50">
      <p className="text-xs text-slate-400 uppercase tracking-wider mb-1">{label}</p>
      <p className={`text-xl font-bold ${positive === undefined ? "text-slate-100" : positive ? "text-green-400" : "text-red-400"}`}>
        {value}
      </p>
      {sub && <p className="text-[10px] text-slate-500 mt-0.5">{sub}</p>}
    </div>
  );
}

// ─── Metrics Comparison Table ───────────────────────────────────────────────
const METRIC_LABELS: Record<string, { label: string; format: (v: number) => string; higherBetter: boolean }> = {
  total_return: { label: "总收益率", format: (v) => `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`, higherBetter: true },
  annual_return: { label: "年化收益", format: (v) => `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`, higherBetter: true },
  max_drawdown: { label: "最大回撤", format: (v) => `-${v.toFixed(2)}%`, higherBetter: false },
  sharpe_ratio: { label: "夏普比率", format: (v) => v.toFixed(3), higherBetter: true },
  win_rate: { label: "胜率", format: (v) => `${v.toFixed(1)}%`, higherBetter: true },
  profit_factor: { label: "盈亏比", format: (v) => v >= 999 ? "∞" : v.toFixed(2), higherBetter: true },
  total_trades: { label: "交易次数", format: (v) => String(v), higherBetter: true },
};

const COMPOSITION_NAMES: Record<string, string> = { weighted: "加权组合", voting: "投票组合" };

function MetricsComparisonTable({
  comparisons,
  atomicStrategies,
  templates,
}: {
  comparisons: Record<string, { performance: Record<string, number>; error?: string }> | null;
  atomicStrategies: Record<string, Record<string, number>> | null;
  templates: Template[];
}) {
  if (!comparisons && !atomicStrategies) {
    return <div className="text-slate-500 text-xs">暂无数据</div>;
  }

  // Build columns: atomic strategies first, then compositions
  const atomicKeys = Object.keys(atomicStrategies || {});
  const compositionKeys = Object.keys(comparisons || {});
  const allKeys = [...atomicKeys, ...compositionKeys];

  // Get strategy name
  const getName = (key: string) => {
    if (COMPOSITION_NAMES[key]) return COMPOSITION_NAMES[key];
    const tpl = templates.find(t => t.id === key);
    return tpl?.name || key.toUpperCase();
  };

  // Check if a composition strategy has error
  const hasError = (key: string): boolean => {
    if (compositionKeys.includes(key)) {
      return !!(comparisons?.[key]?.error);
    }
    return false;
  };

  // Get performance for a key
  const getPerf = (key: string): Record<string, number> | null => {
    if (compositionKeys.includes(key)) {
      // Return null if there's an error or no performance data
      if (comparisons?.[key]?.error || !comparisons?.[key]?.performance) {
        return null;
      }
      return comparisons[key].performance;
    }
    return atomicStrategies?.[key] || null;
  };

  // Calculate best/worst for each metric (excluding error states)
  const metricsToShow = ["total_return", "annual_return", "max_drawdown", "sharpe_ratio", "win_rate", "total_trades"];

  const getBestWorst = (metric: string) => {
    const values: { key: string; value: number }[] = [];
    for (const key of allKeys) {
      // Skip strategies with errors
      if (hasError(key)) continue;
      const perf = getPerf(key);
      if (perf && perf[metric] !== undefined) {
        values.push({ key, value: perf[metric] });
      }
    }
    if (values.length === 0) return { best: null, worst: null };
    const config = METRIC_LABELS[metric];
    values.sort((a, b) => config.higherBetter ? b.value - a.value : a.value - b.value);
    return { best: values[0]?.key, worst: values[values.length - 1]?.key };
  };

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-slate-700">
            <th className="px-3 py-2 text-left text-slate-400 font-medium sticky left-0 bg-slate-900">指标</th>
            {allKeys.map(key => (
              <th
                key={key}
                className={`px-3 py-2 text-right font-medium ${
                  compositionKeys.includes(key)
                    ? "text-purple-400 bg-purple-500/5"
                    : "text-slate-400"
                }`}
              >
                {getName(key)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {metricsToShow.map(metric => {
            const config = METRIC_LABELS[metric];
            const { best, worst } = getBestWorst(metric);
            return (
              <tr key={metric} className="border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors">
                <td className="px-3 py-2 text-slate-300 sticky left-0 bg-slate-900">{config.label}</td>
                {allKeys.map(key => {
                  const isError = hasError(key);
                  const perf = getPerf(key);
                  const value = perf?.[metric] ?? 0;
                  const isBest = key === best;
                  const isWorst = key === worst;
                  const isComposition = compositionKeys.includes(key);
                  // Format return metrics with color
                  const isReturn = metric === "total_return" || metric === "annual_return";
                  const isPositive = value >= 0;
                  return (
                    <td
                      key={key}
                      className={`px-3 py-2 text-right font-mono ${
                        isComposition ? "font-bold bg-purple-500/5" : ""
                      } ${
                        isError ? "text-amber-500" :
                        isBest ? "text-green-400 font-bold" :
                        isWorst && allKeys.length > 2 ? "text-slate-500" :
                        isReturn ? (isPositive ? "text-green-400" : "text-red-400") :
                        metric === "max_drawdown" ? "text-red-400" :
                        "text-slate-300"
                      }`}
                    >
                      {isError ? "计算失败" : config.format(value)}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ─── Weight Distribution Bars ────────────────────────────────────────────────
const WEIGHT_COLORS = [
  "#3b82f6", "#22c55e", "#f97316", "#a855f7", "#06b6d4", "#ec4899", "#eab308", "#14b8a6"
];

function WeightDistributionBars({
  weightDistribution,
  templates,
}: {
  weightDistribution: Record<string, Record<string, number>>;
  templates: Template[];
}) {
  // Get the first composition type that has weights (usually "weighted")
  const compositionType = Object.keys(weightDistribution)[0];
  const weights = weightDistribution[compositionType] || {};
  const entries = Object.entries(weights).filter(([_, w]) => w > 0);

  if (entries.length === 0) {
    return <div className="text-slate-500 text-xs">暂无权重数据</div>;
  }

  const getName = (key: string) => {
    const tpl = templates.find(t => t.id === key);
    return tpl?.name || key.toUpperCase();
  };

  return (
    <div className="space-y-2">
      {entries.map(([key, weight], index) => {
        const color = WEIGHT_COLORS[index % WEIGHT_COLORS.length];
        const pct = (weight * 100).toFixed(1);
        return (
          <div key={key} className="flex items-center gap-3">
            <span className="text-xs text-slate-400 w-16 truncate">{getName(key)}</span>
            <div className="flex-1 h-6 bg-slate-800 rounded-full overflow-hidden">
              <div
                className="h-full rounded-full transition-all"
                style={{
                  width: `${pct}%`,
                  backgroundColor: `${color}99`,
                }}
              />
            </div>
            <span className="text-xs text-slate-300 w-12 text-right font-mono">{pct}%</span>
          </div>
        );
      })}
    </div>
  );
}

// ─── Signal Contribution Card ─────────────────────────────────────────────────
interface StrategySignalStats {
  buy_signals?: number;
  sell_signals?: number;
  signal_rate?: number;
}

interface SignalStatsMeta {
  agreement_rate?: number;
  strategies_count?: number;
}

interface SignalStats {
  [key: string]: StrategySignalStats | SignalStatsMeta | undefined;
}

function SignalContributionCard({
  signalStats,
  templates,
}: {
  signalStats: SignalStats;
  templates: Template[];
}) {
  // Filter out _meta key and get strategy entries
  const entries = Object.entries(signalStats).filter(([key]) => key !== "_meta") as [string, StrategySignalStats][];
  
  if (entries.length === 0) {
    return null;
  }

  const getName = (key: string) => {
    const tpl = templates.find(t => t.id === key);
    return tpl?.name || key.toUpperCase();
  };

  const meta = signalStats._meta as SignalStatsMeta | undefined;
  const agreementRate = meta?.agreement_rate ?? 0;

  return (
    <Card className="bg-slate-900 border-slate-700/50">
      <CardHeader className="pb-3">
        <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
          <Activity className="w-4 h-4 text-orange-400" />
          信号贡献度分析
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Signal Activity */}
        <div>
          <p className="text-xs text-slate-400 mb-3">各策略信号活跃度</p>
          <div className="space-y-3">
            {entries.map(([key, stats]) => {
              if (!stats) return null;
              const buyCount = stats.buy_signals ?? 0;
              const sellCount = stats.sell_signals ?? 0;
              const signalRate = stats.signal_rate ?? 0;
              const totalActive = buyCount + sellCount;
              
              // Calculate percentages within the bar
              // Total bar width = signalRate * 100%
              // Green part = (buyCount / totalActive) * signalRate * 100%
              // Red part = (sellCount / totalActive) * signalRate * 100%
              const totalBarWidth = signalRate * 100;
              const buyPct = totalActive > 0 ? (buyCount / totalActive) * totalBarWidth : 0;
              const sellPct = totalActive > 0 ? (sellCount / totalActive) * totalBarWidth : 0;
              
              return (
                <div key={key} className="flex items-center gap-3">
                  <span className="text-xs text-slate-300 w-20 truncate">{getName(key)}</span>
                  <div className="flex-1 h-5 bg-slate-800 rounded-full overflow-hidden relative">
                    {/* Buy signal (green from left) */}
                    <div 
                      className="absolute left-0 top-0 h-full bg-green-500/60 rounded-l-full" 
                      style={{ width: `${buyPct}%` }} 
                    />
                    {/* Sell signal (red following) */}
                    <div 
                      className="absolute top-0 h-full bg-red-500/60" 
                      style={{ left: `${buyPct}%`, width: `${sellPct}%` }} 
                    />
                  </div>
                  <div className="flex items-center gap-2 w-28">
                    <span className="text-[10px] text-green-400">买{buyCount}</span>
                    <span className="text-[10px] text-red-400">卖{sellCount}</span>
                    <span className="text-[10px] text-slate-500">{(signalRate * 100).toFixed(0)}%</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Strategy Agreement Rate */}
        {meta && (
          <div className="pt-3 border-t border-slate-700/50">
            <div className="flex items-center justify-between">
              <p className="text-xs text-slate-400">策略信号一致率</p>
              <div className="flex items-center gap-2">
                <div className="w-24 h-2 bg-slate-800 rounded-full overflow-hidden">
                  <div 
                    className="h-full bg-amber-500/60 rounded-full" 
                    style={{ width: `${agreementRate * 100}%` }} 
                  />
                </div>
                <span className="text-xs text-amber-400 font-mono">{(agreementRate * 100).toFixed(1)}%</span>
              </div>
            </div>
            <p className="text-[10px] text-slate-500 mt-1">
              {agreementRate > 0.5 
                ? "策略之间信号高度一致，组合效果可能有限" 
                : agreementRate > 0.3 
                  ? "策略信号适度分散，组合具有互补效果"
                  : "策略信号差异较大，组合可能带来良好的分散化效果"}
            </p>
          </div>
        )}

        {/* Legend */}
        <div className="flex items-center gap-4 pt-2">
          <div className="flex items-center gap-1.5">
            <div className="w-3 h-3 bg-green-500/60 rounded" />
            <span className="text-[10px] text-slate-500">买入信号</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="w-3 h-3 bg-red-500/60 rounded" />
            <span className="text-[10px] text-slate-500">卖出信号</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="w-3 h-3 bg-slate-700 rounded" />
            <span className="text-[10px] text-slate-500">中性/持仓</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// ─── Summary Evaluation Card ──────────────────────────────────────────────────
function SummaryEvaluationCard({
  comparisons,
  atomicStrategies,
}: {
  comparisons: Record<string, { performance: Record<string, number> }> | null;
  atomicStrategies: Record<string, Record<string, number>> | null;
}) {
  // Find best atomic strategy
  const atomicEntries = Object.entries(atomicStrategies || {});
  let bestAtomic: { key: string; total_return: number; max_drawdown: number; sharpe_ratio: number } | null = null;
  for (const [key, perf] of atomicEntries) {
    if (!bestAtomic || (perf.total_return ?? 0) > bestAtomic.total_return) {
      bestAtomic = {
        key,
        total_return: perf.total_return ?? 0,
        max_drawdown: perf.max_drawdown ?? 0,
        sharpe_ratio: perf.sharpe_ratio ?? 0,
      };
    }
  }

  // Get best composition (weighted preferred)
  const compositionEntries = Object.entries(comparisons || {});
  const weightedComp = compositionEntries.find(([k]) => k === "weighted")?.[1]?.performance;
  const votingComp = compositionEntries.find(([k]) => k === "voting")?.[1]?.performance;
  const bestComp = weightedComp || votingComp;

  if (!bestComp || !bestAtomic) {
    return null;
  }

  const returnImprovement = bestComp.total_return - bestAtomic.total_return;
  const drawdownImprovement = bestAtomic.max_drawdown - bestComp.max_drawdown;
  const sharpeImprovement = bestComp.sharpe_ratio - bestAtomic.sharpe_ratio;

  return (
    <Card className="bg-slate-900 border-slate-700/50">
      <CardHeader className="pb-3">
        <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 text-green-400" />
          综合评价
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Return Improvement */}
          <div className="p-4 bg-slate-800/50 rounded-xl border border-slate-700/50">
            <p className="text-xs text-slate-400 mb-1">组合收益 vs 最佳单策略</p>
            <p className={`text-xl font-bold font-mono ${returnImprovement >= 0 ? "text-green-400" : "text-red-400"}`}>
              {returnImprovement >= 0 ? "+" : ""}{returnImprovement.toFixed(2)}%
            </p>
            <p className="text-[10px] text-slate-500 mt-1">
              组合 {bestComp.total_return.toFixed(2)}% vs 单策略 {bestAtomic.total_return.toFixed(2)}%
            </p>
          </div>

          {/* Drawdown Improvement */}
          <div className="p-4 bg-slate-800/50 rounded-xl border border-slate-700/50">
            <p className="text-xs text-slate-400 mb-1">组合回撤 vs 最佳单策略</p>
            <p className={`text-xl font-bold font-mono ${drawdownImprovement >= 0 ? "text-green-400" : "text-red-400"}`}>
              {drawdownImprovement >= 0 ? "改善" : "恶化"} {Math.abs(drawdownImprovement).toFixed(2)}%
            </p>
            <p className="text-[10px] text-slate-500 mt-1">
              组合 -{bestComp.max_drawdown.toFixed(2)}% vs 单策略 -{bestAtomic.max_drawdown.toFixed(2)}%
            </p>
          </div>

          {/* Sharpe Ratio */}
          <div className="p-4 bg-slate-800/50 rounded-xl border border-slate-700/50">
            <p className="text-xs text-slate-400 mb-1">夏普比率对比</p>
            <p className="text-xl font-bold font-mono text-slate-100">
              {bestComp.sharpe_ratio.toFixed(3)}
            </p>
            <p className="text-[10px] text-slate-500 mt-1">
              {sharpeImprovement >= 0 ? "优于" : "低于"}最佳单策略 {bestAtomic.sharpe_ratio.toFixed(3)}
            </p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// ─── Delete Confirmation Dialog ─────────────────────────────────────────────
function DeleteConfirmDialog({
  record,
  onConfirm,
  onCancel,
}: {
  record: any;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-slate-900 border border-slate-700 rounded-2xl p-6 w-full max-w-sm shadow-2xl">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 bg-red-500/10 rounded-full flex items-center justify-center">
            <Trash2 className="w-5 h-5 text-red-400" />
          </div>
          <h3 className="text-lg font-bold text-slate-100">确认删除</h3>
        </div>
        <p className="text-sm text-slate-400 mb-1">确定要删除以下回测记录吗？</p>
        <div className="bg-slate-800/50 rounded-xl p-3 mb-5 border border-slate-700/50">
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="text-[10px] bg-blue-500/10 text-blue-400 border-blue-500/20">
              {record.strategy_type}
            </Badge>
            <span className="text-sm text-slate-300">{record.symbol} / {record.interval}</span>
          </div>
          <p className="text-xs text-slate-500 mt-1">
            {new Date(record.created_at).toLocaleString()} · {(record.metrics?.total_trades ?? record.trades?.length ?? 0)} 笔交易
          </p>
        </div>
        <p className="text-xs text-slate-500 mb-5">此操作无法撤销</p>
        <div className="flex gap-3">
          <Button
            onClick={onCancel}
            variant="outline"
            className="flex-1 bg-slate-800 border-slate-700 text-slate-300 hover:bg-slate-700"
          >
            取消
          </Button>
          <Button
            onClick={onConfirm}
            className="flex-1 bg-red-600 hover:bg-red-500 text-white"
          >
            删除
          </Button>
        </div>
      </div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────
export default function BacktestPage() {
  // Templates
  const [templates, setTemplates]       = useState<Template[]>([]);
  const [selectedType, setSelectedType] = useState<string>("ma");
  const [paramValues, setParamValues]   = useState<Record<string, number>>({});

  // Config
  const [symbol, setSymbol]                 = useState("BTCUSDT");
  const [interval, setIntervalVal]          = useState("1d");
  const [limit, setLimit]                   = useState(500);
  const [initialCapital, setInitialCapital] = useState(10000);

  // Date range (optional)
  const [startTime, setStartTime] = useState<string>('');
  const [endTime, setEndTime] = useState<string>('');

  // Run state
  const [running, setRunning]   = useState(false);
  const [error, setError]       = useState<string | null>(null);
  const [result, setResult]     = useState<BacktestResult | null>(null);

  // History
  const [history, setHistory]   = useState<any[]>([]);
  const [deleteTarget, setDeleteTarget] = useState<any>(null); // Record to delete

  // Composition Mode
  const [backtestMode, setBacktestMode] = useState<"single" | "composition" | "wfa">("single");
  const [selectedStrategies, setSelectedStrategies] = useState<string[]>([]);
  const [compositionType, setCompositionType] = useState<"weighted" | "voting">("weighted");
  const [compositionRunning, setCompositionRunning] = useState(false);
  const [compositionError, setCompositionError] = useState<string | null>(null);
  const [compositionResult, setCompositionResult] = useState<any>(null);

  // WFA Mode
  const [wfaRunning, setWfaRunning] = useState(false);
  const [wfaError, setWfaError] = useState<string | null>(null);
  const [wfaResult, setWfaResult] = useState<any>(null);
  const [wfaTrainRatio, setWfaTrainRatio] = useState<number>(0.7);
  const [wfaWindowsCount, setWfaWindowsCount] = useState<number>(5);

  const handleWfaRun = async () => {
    setWfaRunning(true);
    setWfaError(null);
    try {
      const requestBody: Record<string, any> = {
        strategy_type: selectedType,
        symbol,
        interval,
        limit,
        initial_capital: initialCapital,
        train_ratio: wfaTrainRatio,
        n_windows: wfaWindowsCount,
      };
      if (startTime && endTime) {
        requestBody.start_time = new Date(startTime).toISOString();
        requestBody.end_time = new Date(endTime).toISOString();
      }
      const res = await fetch("/api/v1/strategy/wfa/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestBody),
      });
      const data = await res.json();
      if (!res.ok) {
        setWfaError(data.detail || data.message || "WFA 分析失败");
        return;
      }
      setWfaResult(data);
    } catch (e) {
      setWfaError("网络错误: " + String(e));
    } finally {
      setWfaRunning(false);
    }
  };

  const symbols = [
    { value: "BTCUSDT", label: "BTC/USDT" }, { value: "ETHUSDT", label: "ETH/USDT" },
    { value: "SOLUSDT", label: "SOL/USDT" }, { value: "BNBUSDT", label: "BNB/USDT" },
    { value: "DOGEUSDT", label: "DOGE/USDT" }, { value: "XRPUSDT", label: "XRP/USDT" },
  ];
  const intervals = [
    { value: "15m", label: "15分钟" }, { value: "1h", label: "1小时" },
    { value: "4h", label: "4小时" }, { value: "1d", label: "1天" },
    { value: "1w", label: "1周" },   { value: "1M", label: "1月" },
  ];
  const limitOptions = [
    { value: 200, label: "200 根" }, { value: 500, label: "500 根" },
    { value: 1000, label: "1000 根" }, { value: 2000, label: "2000 根" },
  ];

  // Fetch templates
  useEffect(() => {
    fetch("/api/v1/strategy/templates").then(r => r.json()).then(d => {
      setTemplates(d.templates || []);
      if (d.templates?.length) {
        const first = d.templates[0];
        setSelectedType(first.id);
        const defaults: Record<string, number> = {};
        first.params.forEach((p: ParamDef) => { defaults[p.key] = p.default; });
        setParamValues(defaults);
      }
    }).catch(() => {});
  }, []);

  // Update defaults when template changes
  useEffect(() => {
    const tpl = templates.find(t => t.id === selectedType);
    if (!tpl) return;
    const defaults: Record<string, number> = {};
    tpl.params.forEach(p => { defaults[p.key] = p.default; });
    setParamValues(defaults);
  }, [selectedType, templates]);

  // Fetch history
  const fetchHistory = useCallback(() => {
    fetch("/api/v1/strategy/backtest/history?limit=50").then(r => r.json()).then(d => {
      setHistory(d.history || []);
    }).catch(() => {});
  }, []);

  useEffect(() => { fetchHistory(); }, [fetchHistory]);

  // Delete handler
  const handleDeleteRecord = useCallback(async (record: any) => {
    if (!record.id) return;
    try {
      const res = await fetch(`/api/v1/strategy/backtest/history/${record.id}`, {
        method: "DELETE",
      });
      if (res.ok) {
        // Remove from history list
        const newHistory = history.filter(h => h.id !== record.id);
        setHistory(newHistory);
        // Clear current result if it was showing the deleted record
        if (result?.id === record.id) {
          setResult(null);
        }
        // 如果删除后历史列表为空，也清理当前显示
        if (newHistory.length === 0) {
          setResult(null);
        }
      } else {
        const data = await res.json();
        setError(data.detail || "删除失败");
      }
    } catch (e) {
      setError("网络错误，删除失败");
    } finally {
      setDeleteTarget(null);
    }
  }, [result?.id, history]);

  const currentTemplate = templates.find(t => t.id === selectedType);

  // Auto-save params after successful backtest
  const autoSaveParams = async (strategyType: string, params: Record<string, number>) => {
    try {
      await fetch(`/api/v1/strategy/templates/${strategyType}/params`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          params,
          updated_by: "manual_backtest"
        }),
      });
      // Also refresh templates to reflect new defaults
      fetch("/api/v1/strategy/templates")
        .then(r => r.json())
        .then(d => {
          if (Array.isArray(d)) setTemplates(d);
          else if (Array.isArray(d?.templates)) setTemplates(d.templates);
        })
        .catch(() => {});
    } catch (e) {
      console.error("Failed to auto-save params:", e);
    }
  };

  const handleRun = async () => {
    setRunning(true); setError(null);
    try {
      const requestBody: Record<string, any> = {
        strategy_type:   selectedType,
        symbol,
        interval,
        limit,
        initial_capital: initialCapital,
        params:          paramValues,
      };
      // Add date range if both are specified
      if (startTime && endTime) {
        requestBody.start_time = new Date(startTime).toISOString();
        requestBody.end_time = new Date(endTime).toISOString();
      }
      const res = await fetch("/api/v1/strategy/backtest/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestBody),
      });
      const data = await res.json();
      if (!res.ok) { setError(data.detail || "回测失败"); return; }
      setResult(data);
      fetchHistory();
      
      // Auto-save params to database for sync across pages
      autoSaveParams(selectedType, paramValues);
    } catch (e) {
      setError("网络错误，请检查后端连接");
    } finally {
      setRunning(false);
    }
  };

  // Composition backtest handler
  const handleCompositionRun = async () => {
    // Input validation: require at least 2 strategies
    if (selectedStrategies.length < 2) {
      setCompositionError("请至少选择 2 个策略进行组合对比");
      return;
    }
    
    setCompositionRunning(true);
    setCompositionError(null);
    try {
      const res = await fetch("/api/v1/strategy/composition/compare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          atomic_strategies: selectedStrategies,
          symbol,
          interval,
          data_limit: limit,
          initial_capital: initialCapital,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        // Extract detailed error message from response
        const errorMsg = data.detail || data.message || data.error || `请求失败 (${res.status}: ${res.statusText})`;
        setCompositionError(errorMsg);
        return;
      }
      setCompositionResult(data);
    } catch (e) {
      // Log detailed error for debugging
      const errorMessage = e instanceof Error ? e.message : String(e);
      console.error("Composition run error:", errorMessage);
      setCompositionError(`网络错误: ${errorMessage}`);
    } finally {
      setCompositionRunning(false);
    }
  };

  const m = result?.metrics;

  return (
    <div className="min-h-screen bg-slate-950">
      {/* Header */}
      <header className="border-b border-slate-800 bg-slate-900/50 backdrop-blur-sm sticky top-0 z-40">
        <div className="container mx-auto px-4 py-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 bg-gradient-to-br from-blue-500 to-purple-600 rounded-xl flex items-center justify-center">
                <BarChart3 className="w-5 h-5 text-white" />
              </div>
              <div>
                <h1 className="text-lg font-bold text-slate-100">QuantAgent OS</h1>
                <p className="text-[10px] text-slate-400">策略回测可视化</p>
              </div>
            </div>
            <nav className="hidden md:flex items-center gap-1">
              <Link href="/dashboard" className="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-100 hover:bg-slate-800 rounded-lg transition-all flex items-center gap-1.5">
                <LayoutDashboard className="w-4 h-4" /> 仪表盘
              </Link>
              <span className="px-3 py-1.5 text-sm text-blue-400 bg-blue-500/10 rounded-lg border border-blue-500/20 font-medium flex items-center gap-1.5">
                <BarChart2 className="w-4 h-4" /> 回测
              </span>
              <Link href="/replay" className="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-100 hover:bg-slate-800 rounded-lg transition-all flex items-center gap-1.5">
                <History className="w-4 h-4" /> 历史回放
              </Link>
              <Link href="/strategies" className="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-100 hover:bg-slate-800 rounded-lg transition-all flex items-center gap-1.5">
                <BookOpen className="w-4 h-4" /> 策略库
              </Link>
              <Link href="/terminal" className="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-100 hover:bg-slate-800 rounded-lg transition-all flex items-center gap-1.5">
                <Terminal className="w-4 h-4" /> 终端
              </Link>
            </nav>
          </div>
        </div>
      </header>

      <main className="container mx-auto px-4 py-6">
        {/* Mode Switcher Tab */}
        <div className="flex items-center gap-1 bg-slate-800/50 p-1 rounded-xl border border-slate-700/50 mb-6">
          <button
            onClick={() => setBacktestMode("single")}
            className={`px-4 py-2 text-sm rounded-lg transition-all ${
              backtestMode === "single"
                ? "bg-blue-600/20 text-blue-400 border border-blue-500/30 font-medium"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <div className="flex items-center gap-2">
              <Activity className="w-4 h-4" />
              单一策略
            </div>
          </button>
          <button
            onClick={() => setBacktestMode("composition")}
            className={`px-4 py-2 text-sm rounded-lg transition-all ${
              backtestMode === "composition"
                ? "bg-purple-600/20 text-purple-400 border border-purple-500/30 font-medium"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <div className="flex items-center gap-2">
              <Layers className="w-4 h-4" />
              策略组合
            </div>
          </button>
          <button
            onClick={() => setBacktestMode("wfa")}
            className={`px-4 py-2 text-sm rounded-lg transition-all ${
              backtestMode === "wfa"
                ? "bg-orange-600/20 text-orange-400 border border-orange-500/30 font-medium"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <div className="flex items-center gap-2">
              <RefreshCw className="w-4 h-4" />
              推进分析 (WFA)
            </div>
          </button>
        </div>

        {/* Single Strategy Mode */}
        {backtestMode === "single" && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* ── Left: Config Panel ── */}
            <div className="lg:col-span-1 space-y-4">
            {/* Strategy Selection */}
            <Card className="bg-slate-900 border-slate-700/50">
              <CardHeader className="pb-3">
                <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
                  <div className="w-6 h-6 bg-blue-500/10 rounded flex items-center justify-center border border-blue-500/20">
                    <Activity className="w-3.5 h-3.5 text-blue-400" />
                  </div>
                  选择策略
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="space-y-2">
                  {templates.map(t => (
                    <button
                      key={t.id}
                      onClick={() => setSelectedType(t.id)}
                      className={`w-full text-left p-3 rounded-xl border transition-all ${
                        selectedType === t.id
                          ? "bg-blue-600/20 border-blue-500/50 text-blue-300"
                          : "bg-slate-800/50 border-slate-700/50 text-slate-400 hover:text-slate-200 hover:border-slate-600"
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <p className="font-medium text-sm">{t.name}</p>
                        {selectedType === t.id && <CheckCircle2 className="w-4 h-4 text-blue-400" />}
                      </div>
                      <p className="text-[11px] mt-0.5 opacity-70">{(t.description || '').slice(0, 40)}…</p>
                    </button>
                  ))}
                </div>
              </CardContent>
            </Card>

            {/* Strategy Parameters */}
            {currentTemplate && currentTemplate.params.length > 0 && (
              <Card className="bg-slate-900 border-slate-700/50">
                <CardHeader className="pb-3">
                  <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
                    <div className="w-6 h-6 bg-purple-500/10 rounded flex items-center justify-center border border-purple-500/20">
                      <Activity className="w-3.5 h-3.5 text-purple-400" />
                    </div>
                    策略参数
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  {currentTemplate.params.map(p => (
                    <div key={p.key}>
                      <div className="flex items-center justify-between mb-1.5">
                        <div className="flex items-center gap-1.5">
                          <label className="text-xs text-slate-300">{p.label}</label>
                          {p.description && (
                            <div className="group relative">
                              <HelpCircle className="w-3.5 h-3.5 text-slate-500 hover:text-blue-400 cursor-help transition-colors" />
                              <div className="absolute left-1/2 -translate-x-1/2 bottom-full mb-2 w-56 p-2.5 bg-slate-800 border border-slate-600 rounded-lg shadow-xl opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all z-50">
                                <p className="text-[11px] text-slate-300 leading-relaxed">{p.description}</p>
                                <div className="absolute left-1/2 -translate-x-1/2 top-full -mt-1 border-4 border-transparent border-t-slate-600" />
                              </div>
                            </div>
                          )}
                        </div>
                        <span className="text-xs font-mono text-blue-400 bg-blue-500/10 px-2 py-0.5 rounded">
                          {paramValues[p.key] ?? p.default}
                        </span>
                      </div>
                      <input
                        type="range"
                        min={p.min}
                        max={p.max}
                        step={p.step ?? (p.type === "int" ? 1 : 0.5)}
                        value={paramValues[p.key] ?? p.default}
                        onChange={e => setParamValues(prev => ({
                          ...prev,
                          [p.key]: p.type === "int" ? parseInt(e.target.value) : parseFloat(e.target.value),
                        }))}
                        className="w-full h-1.5 bg-slate-700 rounded-full appearance-none cursor-pointer accent-blue-500"
                      />
                      <div className="flex justify-between mt-0.5">
                        <span className="text-[9px] text-slate-600">{p.min}</span>
                        <span className="text-[9px] text-slate-600">{p.max}</span>
                      </div>
                    </div>
                  ))}
                </CardContent>
              </Card>
            )}

            {/* Market Config */}
            <MarketConfigPanel
              symbol={symbol} setSymbol={setSymbol}
              interval={interval} setIntervalVal={setIntervalVal}
              limit={limit} setLimit={setLimit}
              startTime={startTime} setStartTime={setStartTime}
              endTime={endTime} setEndTime={setEndTime}
              initialCapital={initialCapital} setInitialCapital={setInitialCapital}
              symbols={symbols} intervals={intervals} limitOptions={limitOptions}
              accentColor="blue"
            />

            {/* Run Button */}
            <Button
              onClick={handleRun}
              disabled={running}
              className="w-full bg-blue-600 hover:bg-blue-500 text-white font-bold py-3 rounded-xl text-sm"
            >
              {running
                ? <><RefreshCw className="w-4 h-4 animate-spin mr-2" />回测运行中...</>
                : <><Play className="w-4 h-4 mr-2" />运行回测</>}
            </Button>

            {error && (
              <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-xl text-red-400 text-xs flex items-start gap-2">
                <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                {error}
              </div>
            )}
          </div>

          {/* ── Right: Results ── */}
          <div className="lg:col-span-2 space-y-6">
            {!result ? (
              <div className="flex flex-col items-center justify-center min-h-[400px] text-slate-500 space-y-4">
                <div className="w-20 h-20 bg-slate-800/50 rounded-2xl flex items-center justify-center border border-slate-700/50">
                  <BarChart2 className="w-10 h-10 opacity-30" />
                </div>
                <div className="text-center">
                  <p className="text-base font-medium text-slate-400">选择策略并运行回测</p>
                  <p className="text-sm text-slate-600 mt-1">结果将在此处显示，包含资产曲线和详细指标</p>
                </div>
              </div>
            ) : (
              <>
                {/* Result Header */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <Badge variant="outline" className="bg-blue-500/10 text-blue-400 border-blue-500/20 text-xs">
                      {result.strategy_type.toUpperCase()}
                    </Badge>
                    <Badge variant="outline" className="bg-slate-700 text-slate-300 border-slate-600 text-xs">
                      {result.symbol} / {result.interval}
                    </Badge>
                    <span className="text-xs text-slate-500">{(result.metrics?.total_trades ?? result.trades?.length ?? 0)} 笔交易</span>
                  </div>
                  <span className="text-xs text-slate-500">{new Date(result.created_at).toLocaleString()}</span>
                </div>

                {/* Metrics Grid */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  <MetricCard
                    label="总收益率"
                    value={`${(m!.total_return ?? 0) >= 0 ? "+" : ""}${(m!.total_return ?? 0).toFixed(2)}%`}
                    positive={(m!.total_return ?? 0) >= 0}
                  />
                  <MetricCard
                    label="年化收益率"
                    value={`${(m!.annual_return ?? 0) >= 0 ? "+" : ""}${(m!.annual_return ?? 0).toFixed(2)}%`}
                    positive={(m!.annual_return ?? 0) >= 0}
                  />
                  <MetricCard
                    label="最大回撤"
                    value={`-${(m!.max_drawdown ?? 0).toFixed(2)}%`}
                    positive={false}
                    sub="越小越好"
                  />
                  <MetricCard
                    label="夏普比率"
                    value={(m!.sharpe_ratio ?? 0).toFixed(3)}
                    positive={(m!.sharpe_ratio ?? 0) >= 1}
                    sub={(m!.sharpe_ratio ?? 0) >= 2 ? "优秀" : (m!.sharpe_ratio ?? 0) >= 1 ? "良好" : (m!.sharpe_ratio ?? 0) >= 0.5 ? "一般" : "较差"}
                  />
                  <MetricCard label="胜率" value={`${(m!.win_rate ?? 0).toFixed(1)}%`} positive={(m!.win_rate ?? 0) >= 50} />
                  <MetricCard label="盈亏比" value={(m!.profit_factor ?? 0) >= 999 ? "∞" : (m!.profit_factor ?? 0).toFixed(2)} positive={(m!.profit_factor ?? 0) >= 1.5} />
                  <MetricCard label="总交易次数" value={String(m!.total_trades ?? 0)} />
                  <MetricCard
                    label="最终资金"
                    value={`$${(m!.final_capital ?? m!.initial_capital ?? 10000).toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
                    positive={(m!.final_capital ?? m!.initial_capital ?? 10000) >= (m!.initial_capital ?? 10000)}
                    sub={`初始 $${(m!.initial_capital ?? 10000).toLocaleString()}`}
                  />
                </div>

                {/* Equity Curve */}
                <Card className="bg-slate-900 border-slate-700/50">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
                      <TrendingUp className="w-4 h-4 text-blue-400" />
                      资产曲线
                      <span className="text-xs font-normal text-slate-400 ml-1">({(result.equity_curve || []).length} 个数据点)</span>
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="p-0 pb-2">
                    <EquityCurveChart
                      data={result.equity_curve || []}
                      baselineData={result.baseline_curve ?? []}
                      markers={result.markers ?? []}
                      initialCapital={m!.initial_capital}
                    />
                  </CardContent>
                </Card>

                {/* Trade List */}
                {(result.trades || []).length > 0 && (
                  <Card className="bg-slate-900 border-slate-700/50">
                    <CardHeader className="pb-3">
                      <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
                        <Clock className="w-4 h-4 text-purple-400" />
                        交易记录
                        <span className="text-xs font-normal text-slate-400">（前 {Math.min((result.trades || []).length, 20)} 笔，共 {(result.trades || []).length} 笔）</span>
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="p-0 pb-2">
                      <div className="overflow-x-auto">
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="border-b border-slate-800">
                              {["建仓时间", "平仓时间", "建仓价", "平仓价", "数量", "盈亏", "盈亏%"].map(h => (
                                <th key={h} className="px-3 py-2 text-left text-slate-400 font-medium">{h}</th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {(result.trades || []).slice(0, 20).map((t, i) => (
                              <tr key={i} className="border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors">
                                <td className="px-3 py-2 text-slate-400 font-mono">{t.entry_time.slice(0, 16)}</td>
                                <td className="px-3 py-2 text-slate-400 font-mono">{t.exit_time.slice(0, 16)}</td>
                                <td className="px-3 py-2 text-slate-300 font-mono">${Number(t.entry_price).toLocaleString(undefined, { maximumFractionDigits: 2 })}</td>
                                <td className="px-3 py-2 text-slate-300 font-mono">${Number(t.exit_price).toLocaleString(undefined, { maximumFractionDigits: 2 })}</td>
                                <td className="px-3 py-2 text-slate-400 font-mono">{Number(t.quantity).toFixed(6)}</td>
                                <td className={`px-3 py-2 font-mono font-bold ${t.pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                                  {t.pnl >= 0 ? "+" : ""}${Number(t.pnl).toFixed(2)}
                                </td>
                                <td className={`px-3 py-2 font-mono ${t.pnl_pct >= 0 ? "text-green-400" : "text-red-400"}`}>
                                  {t.pnl_pct >= 0 ? "+" : ""}{Number(t.pnl_pct).toFixed(2)}%
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </CardContent>
                  </Card>
                )}
              </>
            )}

            {/* History */}
            {history.length > 0 && (
              <Card className="bg-slate-900 border-slate-700/50">
                <CardHeader className="pb-3">
                  <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
                    <Clock className="w-4 h-4 text-slate-400" />
                    历史回测记录
                    <span className="text-xs text-slate-500 font-normal">（{history.length} 条）</span>
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-2 max-h-[300px] overflow-y-auto pr-2 custom-scrollbar">
                  {history.map((h, i) => {
                    const ret = h.metrics?.total_return ?? 0;
                    return (
                      <div key={i} className="flex items-center justify-between p-3 bg-slate-800/50 rounded-xl border border-slate-700/50 hover:border-slate-600/50 transition-colors group">
                        <div className="flex items-center gap-3 flex-1 cursor-pointer" onClick={() => setResult(h as any)}>
                          <Badge variant="outline" className="text-[10px] bg-blue-500/10 text-blue-400 border-blue-500/20">
                            {h.strategy_type}
                          </Badge>
                          <span className="text-sm text-slate-300">{h.symbol} / {h.interval}</span>
                          <span className="text-xs text-slate-500">{(h.metrics?.total_trades ?? h.trades?.length ?? 0)} 笔</span>
                        </div>
                        <div className="flex items-center gap-3">
                          <span className={`text-sm font-bold ${ret >= 0 ? "text-green-400" : "text-red-400"}`}>
                            {ret >= 0 ? "+" : ""}{ret.toFixed(2)}%
                          </span>
                          <span className="text-[10px] text-slate-500">{new Date(h.created_at).toLocaleDateString()}</span>
                          <button
                            onClick={(e) => { e.stopPropagation(); setDeleteTarget(h); }}
                            className="p-1.5 rounded-lg text-slate-500 hover:text-red-400 hover:bg-red-500/10 transition-colors opacity-0 group-hover:opacity-100"
                            title="删除记录"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                          <ChevronRight className="w-4 h-4 text-slate-600" />
                        </div>
                      </div>
                    );
                  })}
                </CardContent>
              </Card>
            )}
          </div>
        </div>
        )}

        {/* Composition Mode */}
        {backtestMode === "composition" && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* ── Left: Composition Config Panel ── */}
          <div className="lg:col-span-1 space-y-4">
            {/* Strategy Multi-Select */}
            <Card className="bg-slate-900 border-slate-700/50">
              <CardHeader className="pb-3">
                <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
                  <div className="w-6 h-6 bg-purple-500/10 rounded flex items-center justify-center border border-purple-500/20">
                    <Layers className="w-3.5 h-3.5 text-purple-400" />
                  </div>
                  选择策略（多选）
                  <Badge variant="outline" className="text-[10px] bg-purple-500/10 text-purple-400 border-purple-500/20 ml-auto">
                    已选 {selectedStrategies.length} 个
                  </Badge>
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {templates
                  .filter(t => !["smart_beta", "basis"].includes(t.id))
                  .map(t => (
                    <label
                      key={t.id}
                      className={`flex items-center gap-3 p-2.5 rounded-lg border cursor-pointer transition-all ${
                        selectedStrategies.includes(t.id)
                          ? "border-purple-500/50 bg-purple-500/10"
                          : "border-slate-700/50 hover:border-slate-600/50"
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={selectedStrategies.includes(t.id)}
                        onChange={e => {
                          if (e.target.checked) {
                            setSelectedStrategies(prev => [...prev, t.id]);
                          } else {
                            setSelectedStrategies(prev => prev.filter(s => s !== t.id));
                          }
                        }}
                        className="accent-purple-500 w-4 h-4"
                      />
                      <div className="flex-1">
                        <p className="text-sm text-slate-200">{t.name}</p>
                        <p className="text-[10px] text-slate-500">{(t.description || "").slice(0, 50)}</p>
                      </div>
                    </label>
                  ))}
                {selectedStrategies.length < 2 && (
                  <p className="text-[11px] text-amber-400 mt-2 flex items-center gap-1">
                    <AlertTriangle className="w-3 h-3" />
                    请至少选择 2 个策略
                  </p>
                )}
              </CardContent>
            </Card>

            {/* Composition Type */}
            <Card className="bg-slate-900 border-slate-700/50">
              <CardHeader className="pb-3">
                <CardTitle className="text-slate-100 text-sm">组合方式</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {[
                  { value: "weighted", label: "加权组合", desc: "对各策略信号加权求和" },
                  { value: "voting", label: "投票组合", desc: "多数投票决策机制" }
                ].map(opt => (
                  <button
                    key={opt.value}
                    onClick={() => setCompositionType(opt.value as "weighted" | "voting")}
                    className={`w-full text-left p-3 rounded-xl border transition-all ${
                      compositionType === opt.value
                        ? "bg-purple-600/20 border-purple-500/50 text-purple-300"
                        : "bg-slate-800/50 border-slate-700/50 text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    <p className="font-medium text-sm">{opt.label}</p>
                    <p className="text-[10px] mt-0.5 opacity-70">{opt.desc}</p>
                  </button>
                ))}
              </CardContent>
            </Card>

            {/* Market Config (reused) */}
            <MarketConfigPanel
              symbol={symbol} setSymbol={setSymbol}
              interval={interval} setIntervalVal={setIntervalVal}
              limit={limit} setLimit={setLimit}
              startTime={startTime} setStartTime={setStartTime}
              endTime={endTime} setEndTime={setEndTime}
              initialCapital={initialCapital} setInitialCapital={setInitialCapital}
              symbols={symbols} intervals={intervals} limitOptions={limitOptions}
              accentColor="purple"
            />

            {/* Run Button */}
            <Button
              onClick={handleCompositionRun}
              disabled={compositionRunning || selectedStrategies.length < 2}
              className="w-full bg-purple-600 hover:bg-purple-500 text-white font-bold py-3 rounded-xl text-sm"
            >
              {compositionRunning
                ? <><RefreshCw className="w-4 h-4 animate-spin mr-2" />组合对比运行中...</>
                : <><Play className="w-4 h-4 mr-2" />运行组合对比</>}
            </Button>

            {compositionError && (
              <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-xl text-red-400 text-xs flex items-start gap-2">
                <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                {compositionError}
              </div>
            )}
          </div>

          {/* ── Right: Composition Results ── */}
          <div className="lg:col-span-2 space-y-6">
            {!compositionResult ? (
              <div className="flex flex-col items-center justify-center min-h-[400px] text-slate-500 space-y-4">
                <div className="w-20 h-20 bg-slate-800/50 rounded-2xl flex items-center justify-center border border-slate-700/50">
                  <Layers className="w-10 h-10 opacity-30" />
                </div>
                <div className="text-center">
                  <p className="text-base font-medium text-slate-400">选择策略组合并运行对比</p>
                  <p className="text-sm text-slate-600 mt-1">选择至少 2 个策略，运行后查看组合与单策略的对比结果</p>
                </div>
              </div>
            ) : compositionResult.success === false ? (
              <div className="flex flex-col items-center justify-center min-h-[400px] text-slate-500 space-y-4">
                <div className="w-20 h-20 bg-red-500/10 rounded-2xl flex items-center justify-center border border-red-500/20">
                  <AlertTriangle className="w-10 h-10 text-red-400" />
                </div>
                <div className="text-center">
                  <p className="text-base font-medium text-red-400">组合对比运行失败</p>
                  <p className="text-sm text-slate-500 mt-1">{compositionResult.message || "请检查策略参数或数据后重试"}</p>
                </div>
              </div>
            ) : !compositionResult.comparisons || Object.keys(compositionResult.comparisons || {}).length === 0 ? (
              <div className="flex flex-col items-center justify-center min-h-[400px] text-slate-500 space-y-4">
                <div className="w-20 h-20 bg-amber-500/10 rounded-2xl flex items-center justify-center border border-amber-500/20">
                  <Info className="w-10 h-10 text-amber-400" />
                </div>
                <div className="text-center">
                  <p className="text-base font-medium text-amber-400">无有效对比数据</p>
                  <p className="text-sm text-slate-500 mt-1">运行完成但未生成有效结果，请检查数据源或策略配置</p>
                </div>
              </div>
            ) : (
              <>
                {/* Result Title Bar */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <Badge className="bg-purple-500/10 text-purple-400 border-purple-500/20">策略组合对比</Badge>
                    <Badge variant="outline" className="bg-slate-700 text-slate-300 border-slate-600 text-xs">
                      {symbol} / {interval}
                    </Badge>
                    <span className="text-xs text-slate-500">{selectedStrategies.length} 个策略</span>
                  </div>
                  <span className="text-xs text-slate-500">
                    {compositionResult.comparison_time ? new Date(compositionResult.comparison_time).toLocaleString() : ""}
                  </span>
                </div>

                {/* Equity Curve Comparison Chart */}
                <Card className="bg-slate-900 border-slate-700/50">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
                      <TrendingUp className="w-4 h-4 text-purple-400" />
                      权益曲线对比
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="p-0 pb-2">
                    <CompositionCompareChart
                      equityCurves={Object.fromEntries(
                        Object.entries(compositionResult.equity_curves || {}).filter(
                          ([, v]) => v && Array.isArray(v) && v.length > 0
                        )
                      ) as Record<string, { t: string; v: number }[]>}
                      initialCapital={initialCapital}
                      height={360}
                    />
                  </CardContent>
                </Card>

                {/* Metrics Comparison Table */}
                <Card className="bg-slate-900 border-slate-700/50">
                  <CardHeader className="pb-3">
                    <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
                      <BarChart2 className="w-4 h-4 text-blue-400" />
                      指标对比
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <MetricsComparisonTable
                      comparisons={compositionResult.comparisons}
                      atomicStrategies={compositionResult.atomic_strategies}
                      templates={templates}
                    />
                  </CardContent>
                </Card>

                {/* Weight Distribution */}
                {compositionResult.weight_distribution && (
                  <Card className="bg-slate-900 border-slate-700/50">
                    <CardHeader className="pb-3">
                      <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
                        <Layers className="w-4 h-4 text-green-400" />
                        权重分布
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      <WeightDistributionBars
                        weightDistribution={compositionResult.weight_distribution}
                        templates={templates}
                      />
                    </CardContent>
                  </Card>
                )}

                {/* Summary Evaluation Card */}
                <SummaryEvaluationCard
                  comparisons={compositionResult.comparisons}
                  atomicStrategies={compositionResult.atomic_strategies}
                />

                {/* Signal Contribution Analysis */}
                {compositionResult?.signal_stats && Object.keys(compositionResult.signal_stats).length > 0 && (
                  <SignalContributionCard
                    signalStats={compositionResult.signal_stats}
                    templates={templates}
                  />
                )}
              </>
            )}
          </div>
        </div>
        )}

        {/* WFA Mode */}
        {backtestMode === "wfa" && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-1 space-y-4">
              {/* Strategy Selection */}
              <Card className="bg-slate-900 border-slate-700/50">
                <CardHeader className="pb-3">
                  <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
                    <div className="w-6 h-6 bg-orange-500/10 rounded flex items-center justify-center border border-orange-500/20">
                      <RefreshCw className="w-3.5 h-3.5 text-orange-400" />
                    </div>
                    策略选择
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <Select value={selectedType} onValueChange={setSelectedType}>
                    <SelectTrigger className="bg-slate-800 border-slate-700 text-slate-200">
                      <SelectValue placeholder="选择策略" />
                    </SelectTrigger>
                    <SelectContent className="bg-slate-800 border-slate-700">
                      {templates.map(t => (
                        <SelectItem key={t.id} value={t.id} className="text-slate-200 focus:bg-slate-700">
                          {t.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </CardContent>
              </Card>

              {/* WFA Specific Config */}
              <Card className="bg-slate-900 border-slate-700/50">
                <CardHeader className="pb-3">
                  <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
                    <div className="w-6 h-6 bg-orange-500/10 rounded flex items-center justify-center border border-orange-500/20">
                      <Layers className="w-3.5 h-3.5 text-orange-400" />
                    </div>
                    WFA 参数
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div>
                    <div className="flex justify-between text-xs text-slate-300 mb-1">
                      <label>训练集比例 (Train Ratio)</label>
                      <span>{(wfaTrainRatio * 100).toFixed(0)}%</span>
                    </div>
                    <input
                      type="range"
                      min={0.3} max={0.9} step={0.05}
                      value={wfaTrainRatio}
                      onChange={e => setWfaTrainRatio(parseFloat(e.target.value))}
                      className="w-full h-1.5 bg-slate-700 rounded-full appearance-none cursor-pointer accent-orange-500"
                    />
                  </div>
                  <div>
                    <div className="flex justify-between text-xs text-slate-300 mb-1">
                      <label>窗口数量 (Windows)</label>
                      <span>{wfaWindowsCount}</span>
                    </div>
                    <input
                      type="range"
                      min={3} max={20} step={1}
                      value={wfaWindowsCount}
                      onChange={e => setWfaWindowsCount(parseInt(e.target.value))}
                      className="w-full h-1.5 bg-slate-700 rounded-full appearance-none cursor-pointer accent-orange-500"
                    />
                  </div>
                </CardContent>
              </Card>

              <MarketConfigPanel
                symbol={symbol} setSymbol={setSymbol}
                interval={interval} setIntervalVal={setIntervalVal}
                limit={limit} setLimit={setLimit}
                startTime={startTime} setStartTime={setStartTime}
                endTime={endTime} setEndTime={setEndTime}
                initialCapital={initialCapital} setInitialCapital={setInitialCapital}
                symbols={symbols} intervals={intervals} limitOptions={limitOptions}
                accentColor="orange"
              />

              {/* Run Button */}
              <Button
                onClick={handleWfaRun}
                disabled={wfaRunning}
                className="w-full bg-orange-600 hover:bg-orange-500 text-white font-bold py-3 rounded-xl text-sm"
              >
                {wfaRunning
                  ? <><RefreshCw className="w-4 h-4 animate-spin mr-2" />WFA 分析中...</>
                  : <><Play className="w-4 h-4 mr-2" />运行 WFA</>}
              </Button>

              {wfaError && (
                <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-xl text-red-400 text-xs flex items-start gap-2">
                  <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                  {wfaError}
                </div>
              )}
            </div>

            <div className="lg:col-span-2 space-y-6">
              {!wfaResult ? (
                <div className="flex flex-col items-center justify-center min-h-[400px] text-slate-500 space-y-4">
                  <div className="w-20 h-20 bg-slate-800/50 rounded-2xl flex items-center justify-center border border-slate-700/50">
                    <RefreshCw className="w-10 h-10 opacity-30" />
                  </div>
                  <div className="text-center">
                    <p className="text-base font-medium text-slate-400">运行推进分析 (Walk-Forward Analysis)</p>
                    <p className="text-sm text-slate-600 mt-1">通过滚动窗口回测验证策略参数的稳定性和鲁棒性</p>
                  </div>
                </div>
              ) : (
                <>
                  {/* WFA Result Header */}
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <Badge className="bg-orange-500/10 text-orange-400 border-orange-500/20">WFA 结果</Badge>
                      <Badge variant="outline" className="bg-slate-700 text-slate-300 border-slate-600 text-xs">
                        {symbol} / {interval}
                      </Badge>
                      <span className="text-xs text-slate-500">{wfaResult.windows?.length || 0} 个窗口</span>
                    </div>
                  </div>

                  {/* Overview Metrics */}
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    <MetricCard
                      label="整体 WFE"
                      value={`${(wfaResult.overall_wfe * 100).toFixed(2)}%`}
                      positive={wfaResult.overall_wfe >= 0.5}
                      sub={wfaResult.overall_wfe >= 0.5 ? "参数具有一致性" : "存在过拟合风险"}
                    />
                    <MetricCard
                      label="平均样本外年化"
                      value={`${(wfaResult.average_test_annual_return * 100).toFixed(2)}%`}
                      positive={wfaResult.average_test_annual_return >= 0}
                    />
                    <MetricCard
                      label="平均胜率"
                      value={`${((wfaResult.windows?.reduce((acc: number, w: any) => acc + (w.test_metrics?.win_rate || 0), 0) / (wfaResult.windows?.length || 1))).toFixed(1)}%`}
                      positive={true}
                    />
                    <MetricCard
                      label="测试集样本数"
                      value={String(wfaResult.total_test_trades || 0)}
                    />
                  </div>

                  {/* Equity Curve with Window Boundaries */}
                  <Card className="bg-slate-900 border-slate-700/50">
                    <CardHeader className="pb-2">
                      <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
                        <TrendingUp className="w-4 h-4 text-orange-400" />
                        样本外拼接净值曲线 (OOS Equity Curve)
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="p-0 pb-2">
                      <EquityCurveChart
                        data={wfaResult.oos_equity_curve || []}
                        initialCapital={initialCapital}
                        windowBoundaries={wfaResult.windows?.map((w: any) => ({
                          time: w.test_start,
                          label: `W${w.window_index}`,
                          color: "#f59e0b"
                        }))}
                      />
                    </CardContent>
                  </Card>

                  {/* WFE and Param Stability Charts */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <Card className="bg-slate-900 border-slate-700/50">
                      <CardHeader className="pb-2">
                        <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
                          <BarChart3 className="w-4 h-4 text-orange-400" />
                          各窗口 WFE 对比
                        </CardTitle>
                      </CardHeader>
                      <CardContent>
                        <WfeCompareChart data={wfaResult.windows || []} height={250} />
                      </CardContent>
                    </Card>

                    <Card className="bg-slate-900 border-slate-700/50">
                      <CardHeader className="pb-2">
                        <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
                          <Activity className="w-4 h-4 text-orange-400" />
                          最优参数演变
                        </CardTitle>
                      </CardHeader>
                      <CardContent>
                        <ParamStabilityChart data={wfaResult.windows || []} height={250} />
                      </CardContent>
                    </Card>
                  </div>

                  {/* Window Details Table */}
                  <Card className="bg-slate-900 border-slate-700/50">
                    <CardHeader className="pb-3">
                      <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
                        <Layers className="w-4 h-4 text-slate-400" />
                        滚动窗口详情
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="p-0">
                      <div className="overflow-x-auto">
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="border-b border-slate-800 bg-slate-900">
                              <th className="px-3 py-2 text-left text-slate-400 font-medium">窗口</th>
                              <th className="px-3 py-2 text-left text-slate-400 font-medium">训练集周期</th>
                              <th className="px-3 py-2 text-left text-slate-400 font-medium">测试集周期</th>
                              <th className="px-3 py-2 text-right text-slate-400 font-medium">IS 年化</th>
                              <th className="px-3 py-2 text-right text-slate-400 font-medium">OOS 年化</th>
                              <th className="px-3 py-2 text-right text-slate-400 font-medium">WFE</th>
                              <th className="px-3 py-2 text-left text-slate-400 font-medium">最优参数</th>
                            </tr>
                          </thead>
                          <tbody>
                            {(wfaResult.windows || []).map((w: any, i: number) => {
                              const wfe = w.wfe || 0;
                              const isReturn = w.train_metrics?.annual_return || 0;
                              const oosReturn = w.test_metrics?.annual_return || 0;
                              return (
                                <tr key={i} className="border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors">
                                  <td className="px-3 py-2 text-slate-300 font-medium">W{w.window_index}</td>
                                  <td className="px-3 py-2 text-slate-500 font-mono text-[10px]">
                                    {new Date(w.train_start).toLocaleDateString()} - {new Date(w.train_end).toLocaleDateString()}
                                  </td>
                                  <td className="px-3 py-2 text-slate-500 font-mono text-[10px]">
                                    {new Date(w.test_start).toLocaleDateString()} - {new Date(w.test_end).toLocaleDateString()}
                                  </td>
                                  <td className={`px-3 py-2 text-right font-mono ${isReturn >= 0 ? "text-green-400" : "text-red-400"}`}>
                                    {(isReturn * 100).toFixed(2)}%
                                  </td>
                                  <td className={`px-3 py-2 text-right font-mono ${oosReturn >= 0 ? "text-green-400" : "text-red-400"}`}>
                                    {(oosReturn * 100).toFixed(2)}%
                                  </td>
                                  <td className={`px-3 py-2 text-right font-mono font-bold ${wfe >= 0.5 ? "text-green-400" : wfe > 0 ? "text-amber-400" : "text-red-400"}`}>
                                    {(wfe * 100).toFixed(2)}%
                                  </td>
                                  <td className="px-3 py-2">
                                    <div className="flex flex-wrap gap-1">
                                      {Object.entries(w.best_params || {}).map(([k, v]) => (
                                        <Badge key={k} variant="outline" className="text-[9px] px-1 py-0 bg-slate-800 border-slate-700 text-slate-400">
                                          {k}: {String(v)}
                                        </Badge>
                                      ))}
                                    </div>
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    </CardContent>
                  </Card>
                </>
              )}
            </div>
          </div>
        )}
      </main>

      {/* Delete Confirmation Dialog */}
      {deleteTarget && (
        <DeleteConfirmDialog
          record={deleteTarget}
          onConfirm={() => handleDeleteRecord(deleteTarget)}
          onCancel={() => setDeleteTarget(null)}
        />
      )}
    </div>
  );
}
