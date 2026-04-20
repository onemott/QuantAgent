"use client";

import { useEffect, useRef, useState, useCallback, Suspense } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { 
  BarChart3, TrendingUp, TrendingDown, Activity, RefreshCw, 
  Play, Pause, FastForward, SkipForward, Clock, DollarSign, 
  BarChart2, Percent, AlertTriangle, CheckCircle2, Terminal, 
  BookOpen, LayoutDashboard, Calendar as CalendarIcon, History, Shield, Zap, Info, X,
  ArrowLeft, ChevronRight, ChevronDown, ChevronUp, ChevronLeft, Settings2, MousePointer2,
  Bookmark, BookmarkCheck, Trash2, List
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectSeparator, SelectTrigger, SelectValue } from "@/components/ui/select";
import { DateRangePicker, generateQuickRanges } from "@/components/ui/date-range-picker";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { format } from "date-fns";
import { useSearchParams, useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { ReplayProvider, useReplayStore } from "@/lib/replay-store";
import { EquityCurveChart, TradeMarker } from "@/components/charts/EquityCurveChart";
import KlineChart from "@/components/charts/KlineChart";
import TradeList from "@/components/charts/TradeList";
import PositionPanel from "@/components/charts/PositionPanel";
import { AtomicStrategyPanel, AtomicStrategyConfig, StrategyTemplate } from "@/components/replay/AtomicStrategyPanel";
import EliminationHistory from "@/components/monitor/EliminationHistory";
import WeightEvolutionChart from "@/components/replay/WeightEvolutionChart";

// Dynamic import with SSR disabled to avoid hydration mismatch with localStorage state
const ReplayContent = dynamic(() => Promise.resolve(ReplayContentWithHydrationFix), {
  ssr: false,
  loading: () => <div className="min-h-screen bg-slate-950 flex items-center justify-center text-slate-400">Loading Replay...</div>
});

// ─── Types ────────────────────────────────────────────────────────────────────

interface ReplaySession {replay_session_id: string;strategy_id: number;symbol: string;start_time: string;end_time: string;speed: number;initial_capital: number;status: "pending" | "running" | "paused" | "completed" | "failed";current_timestamp?: string;created_at: string;is_saved?: boolean;
}

interface ReplayStatus {replay_session_id: string;status: "pending" | "running" | "paused" | "completed" | "failed";current_simulated_time: string;progress: number;pnl: number;equity_curve?: { t: string; v: number }[];
  // 健康状态监控字段
  error_count?: number;
  warnings?: string[];
  bars_processed?: number;
  bars_total?: number;
}

interface ReplayHistoryItem {replay_session_id: string;strategy_id: number;strategy_type: string | null;params: Record<string, any> | null;symbol: string;start_time: string;end_time: string;speed: number;initial_capital: number;status: "pending" | "running" | "paused" | "completed" | "failed";current_timestamp: string | null;is_saved: boolean;created_at: string;pnl: number | null;
  // 新增：来自增强 API 的摘要信息
  summary?: {
    total_return: number | null;
    trade_count: number | null;
    final_equity: number | null;
    win_rate: number | null;
    max_drawdown: number | null;
  } | null;
}

// 会话列表响应类型
interface SessionsResponse {total_count: number;page: number;page_size: number;total_pages: number;sessions: ReplayHistoryItem[];
}

// 后端时间估算响应
interface EstimateTimeResponse {estimated_seconds: number;bar_count: number;notes: string | null;breakdown?: {data_bars: number;interval_seconds: number;simulated_seconds: number;speed: number;
  };
}

interface ReplayTradeStats {replay_session_id: string;total_trades: number;winning_trades: number;losing_trades: number;win_rate: number;total_pnl: number;avg_win: number;avg_loss: number;max_profit: number;max_loss: number;total_fees: number;final_equity: number;
  returns_pct: number;
}

// Dynamic Selection History Record (shared between EliminationHistory and WeightEvolutionChart)
interface DynamicSelectionHistoryRecord {
  id: number;
  evaluation_date: string;
  total_strategies: number;
  surviving_count: number;
  eliminated_count: number;
  eliminated_strategy_ids: string[];
  elimination_reasons: Record<string, string>;
  strategy_weights: Record<string, number>;
  expected_return: number;
  expected_volatility: number;
  expected_sharpe: number;
  created_at: string;
}

// ─── Constants ────────────────────────────────────────────────────────────────
const SYMBOLS = [
  { value: "BTCUSDT", label: "BTC/USDT" }, { value: "ETHUSDT", label: "ETH/USDT" },
  { value: "SOLUSDT", label: "SOL/USDT" }, { value: "BNBUSDT", label: "BNB/USDT" },
];

const SPEEDS = [
  { value: 1, label: "1x (实时)" },
  { value: 10, label: "10x" },
  { value: 60, label: "60x" },
  { value: 100, label: "100x" },
  { value: 500, label: "500x" },
  { value: 1000, label: "1000x" },
  { value: 5000, label: "5000x" },
  { value: 10000, label: "10000x" },
  { value: 50000, label: "50000x" },
  { value: 100000, label: "100000x (超极速)" },
  { value: -1, label: "极速模式 (无延迟)" },
];

// 策略类型推荐周期映射
const STRATEGY_INTERVAL_MAP: Record<string, { interval: string; label: string }> = {
  "ma":      { interval: "15m", label: "15分钟" },
  "rsi":     { interval: "1h",  label: "1小时" },
  "boll":    { interval: "1h",  label: "1小时" },
  "macd":    { interval: "4h",  label: "4小时" },
  "ema_triple": { interval: "1h", label: "1小时" },
  "atr_trend":  { interval: "4h", label: "4小时" },
  "turtle":     { interval: "1d", label: "1天" },
  "ichimoku":    { interval: "4h", label: "4小时" },
  "smart_beta":  { interval: "1h", label: "1小时" },
  "basis":       { interval: "1h", label: "1小时" },
  "dynamic_selection": { interval: "1m", label: "1分钟" },
};

// 快速预设方案
const PRESET_PROFILES = [
  {id: "quick_test",name: "快速测试",desc: "3天范围 + 1000x倍速，适合验证策略逻辑",icon: "[fast]",config: { days: 3, speed: 1000, interval: "15m" }
  },
  {id: "daily_verify",name: "日线验证",desc: "7天日线 + 500x倍速，海龟等趋势策略推荐",icon: "[daily]",config: { days: 7, speed: 500, interval: "1d" }
  },
  {id: "medium_scan",name: "中期扫描",desc: "14天4小时 + 500x倍速，平衡精度与速度",icon: "[scan]",config: { days: 14, speed: 500, interval: "4h" }
  },
  {id: "full_backtest",name: "完整回测",desc: "30天分钟线 + 100x倍速，全面验证",icon: "[full]",config: { days: 30, speed: 100, interval: "1h" }
  },
];

// 计算预计回放时间 - 基于实际数据量
function calculateEstimatedTime(dataPoints: number, interval: string, speed: number): string {
  const intervalSeconds: Record<string, number> = {
    "1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400
  };
  const intervalSec = intervalSeconds[interval] || 60;
  // Total simulated seconds = data points * interval duration
  const totalSimSeconds = dataPoints * intervalSec;
  // Real time needed = simulated / speed (unless speed is -1 for instant)
  const realSeconds = speed === -1 ? 0 : totalSimSeconds / speed;
  
  if (speed === -1) return `极速完成`;
  if (dataPoints === 0) return `无数据`;
  if (realSeconds < 1) return `少于1秒`;
  if (realSeconds < 60) return `约 ${Math.round(realSeconds)} 秒`;
  if (realSeconds < 3600) return `约 ${Math.round(realSeconds / 60)} 分钟`;
  return `约 ${(realSeconds / 3600).toFixed(1)} 小时`;
}

// 格式化实际消耗时间
function formatElapsedTime(seconds: number): string {
  if (seconds < 1) return `${(seconds * 1000).toFixed(0)}毫秒`;
  if (seconds < 60) return `${Math.round(seconds)}秒`;
  if (seconds < 3600) {
    const mins = Math.floor(seconds / 60);
    const secs = Math.round(seconds % 60);
    return secs > 0 ? `${mins}分${secs}秒` : `${mins}分钟`;
  }
  const hours = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  return `${hours}小时${mins > 0 ? `${mins}分` : ""}`;
}

// 基于日期范围估算数据量（基于实际有效数据范围）
function estimateDataPoints(days: number, interval: string): number {
  const intervalSeconds: Record<string, number> = {
    "1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400
  };
  const intervalSec = intervalSeconds[interval] || 60;
  // 假设每天 24 小时,考虑节假日和周末等因素,实际数据约为理论值的 85%
  const theoreticalPerDay = 86400 / intervalSec;
  // Use max(1, ...) to handle 1d interval where 0.85 floors to 0
  const realisticPerDay = Math.max(1, Math.floor(theoreticalPerDay * 0.85));
  return days * realisticPerDay;
}

// 计算理论回放时间（用于与实际时间对比）
// 考虑策略计算开销和高倍速下的性能衰减
function calculateTheoreticalTime(dataPoints: number, interval: string, speed: number): { display: string; seconds: number } {
  const intervalSeconds: Record<string, number> = {
    "1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400
  };
  const intervalSec = intervalSeconds[interval] || 60;
  
  // 基础模拟时间
  const totalSimSeconds = dataPoints * intervalSec;
  
  // 理论回放时间 = 模拟时间 / 倍速
  // 但需要考虑实际开销：高倍速时每根K线的固定计算开销占比增大
  let overheadFactor = 1.0;
  if (speed === -1) {
    // 极速模式：开销因子约1.5（主要来自策略计算）overheadFactor = 1.5;
  } else if (speed >= 1000) {
    // 超高倍速：开销因子约2-3倍（sleep时间很短，计算开销占主导）overheadFactor = 2.5;
  } else if (speed >= 500) {
    // 高倍速：开销因子约1.5-2倍overheadFactor = 1.8;
  } else if (speed >= 100) {
    // 中倍速：开销因子约1.2-1.5倍overheadFactor = 1.3;
  }
  // 低倍速时，sleep时间主导，开销因子接近1
  
  const realSeconds = speed === -1 
    ? (dataPoints * 0.001) * overheadFactor  // 极速：假设每根K线约1ms
    : (totalSimSeconds / speed) * overheadFactor;
  
  let display: string;
  if (speed === -1) {display = "极速完成";
  } else if (realSeconds < 1) {display = "<1秒";
  } else if (realSeconds < 60) {display = `约${Math.round(realSeconds)}秒`;
  } else if (realSeconds < 3600) {display = `约${Math.round(realSeconds / 60)}分钟`;
  } else {display = `约${(realSeconds / 3600).toFixed(1)}小时`;
  }
  
  return { display, seconds: realSeconds };
}

// 支持的 K 线周期
const INTERVALS = [
  { value: "1m",  label: "1分钟" },
  { value: "5m",  label: "5分钟" },
  { value: "15m", label: "15分钟" },
  { value: "1h",  label: "1小时" },
  { value: "4h",  label: "4小时" },
  { value: "1d",  label: "1天" },
];

// Interval 到分钟的映射（用于计算 evaluation_period）
const INTERVAL_MINUTES: Record<string, number> = {
  "1m": 1,
  "5m": 5,
  "15m": 15,
  "1h": 60,
  "4h": 240,
  "1d": 1440,
};

// ─── Main Page ────────────────────────────────────────────────────────────────
export default function ReplayPage() {
  return (
    <ReplayProvider>
      <ReplayContent />
    </ReplayProvider>
  );
}

function ReplayContentWithHydrationFix() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const urlSessionId = searchParams.get("session_id");
  
  // ─── Global Store ────────────────────────────────────────────────────────────
  const { state: storeState,setSession: setStoreSession,setStatus: setStoreStatus,clearSession: clearStoreSession,startPolling: startStorePolling,stopPolling: stopStorePolling,restoreSession: restoreStoreSession
  } = useReplayStore();

  // Templates
  const [templates, setTemplates] = useState<StrategyTemplate[]>([]);
  const [selectedType, setSelectedType] = useState<string>("ma");
  const [paramValues, setParamValues] = useState<Record<string, number>>({});

  // Config - Use stable initial values, update after mount
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [interval, setInterval] = useState("15m");  // K 线周期
  const [dateRange, setDateRange] = useState({
    // Use a fixed date range initially to avoid hydration mismatch
    start: "2026-03-10T00:00:00.000Z",
    end: "2026-03-17T23:59:59.999Z"
  });
  const [dateInitialized, setDateInitialized] = useState(false);
  const [speed, setSpeed] = useState(60);
  const [initialCapital, setInitialCapital] = useState(100000);
  const [validDates, setValidDates] = useState<string[]>([]);

  // Local UI state (toast, modals, etc.)
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<{ message: string; type: "error" | "info" | "success" } | null>(null);
  const [quickBacktestLoading, setQuickBacktestLoading] = useState(false);

  // Helper: convert any value to a safe string for toast/error display
  const safeMsg = (val: unknown, fallback: string): string => {
    if (typeof val === 'string') return val;
    if (val == null) return fallback;
    if (typeof val === 'object' && 'type' in (val as object) && 'loc' in (val as object)) {
      const e = val as { msg?: unknown };
      return e.msg != null ? String(e.msg) : fallback;
    }try { return JSON.stringify(val); } catch { return fallback; }
  };

  // Jump Modal
  const [showJumpModal, setShowJumpModal] = useState(false);
  const [jumpDate, setJumpDate] = useState<Date | undefined>(new Date());
  const [jumpTime, setJumpTime] = useState<string>("12:00");

  // History Panel
  const [showHistoryPanel, setShowHistoryPanel] = useState(false);
  const [historyList, setHistoryList] = useState<ReplayHistoryItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [showSavedOnly, setShowSavedOnly] = useState(false);
  const [expandedSessionId, setExpandedSessionId] = useState<string | null>(null);
  const [sessionStats, setSessionStats] = useState<Record<string, ReplayTradeStats>>({});
  const [loadingStatsId, setLoadingStatsId] = useState<string | null>(null);
  // 新增：分页和筛选状态
  const [historyPage, setHistoryPage] = useState(1);
  const [historyTotalPages, setHistoryTotalPages] = useState(1);
  const [historyTotalCount, setHistoryTotalCount] = useState(0);
  const [statusFilter, setStatusFilter] = useState<string>("all"); // all, completed, running, failed, paused
  const [strategyFilter, setStrategyFilter] = useState<string>("all");
  // 后端时间估算状态
  const [serverEstimate, setServerEstimate] = useState<EstimateTimeResponse | null>(null);
  const [estimateLoading, setEstimateLoading] = useState(false);
  // 历史列表快速回测 loading
  const [historyQuickBacktestId, setHistoryQuickBacktestId] = useState<string | null>(null);

  // Equity Curve State
  const [equityCurveData, setEquityCurveData] = useState<{ t: string; v: number }[]>([]);
  const [baselineCurveData, setBaselineCurveData] = useState<{ t: string; v: number }[]>([]);
  const [tradeMarkers, setTradeMarkers] = useState<TradeMarker[]>([]);

  // New chart data states
  const [klineData, setKlineData] = useState<any[]>([]);
  const [indicatorData, setIndicatorData] = useState<Record<string, any[]>>({});
  const [tradeList, setTradeList] = useState<any[]>([]);
  const [positionInfo, setPositionInfo] = useState<any>(null);

  // Preset Panel
  const [showPresets, setShowPresets] = useState(false);

  // Progress Bar Interaction
  const [hoverProgress, setHoverProgress] = useState<{ x: number; time: string; percent: number } | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [showProgressHint, setShowProgressHint] = useState(false);
  
  // Warning Panel State
  const [showWarningPanel, setShowWarningPanel] = useState(false);

  // Atomic Strategy Panel State (for dynamic_selection)
  const [atomicStrategies, setAtomicStrategies] = useState<AtomicStrategyConfig[]>([
    { strategy_id: "ds_ma_1", strategy_type: "ma", params: { fast_period: 10, slow_period: 30 } },
    { strategy_id: "ds_rsi_1", strategy_type: "rsi", params: { rsi_period: 14, oversold: 30, overbought: 70 } },
  ]);
  const [evaluationPeriod, setEvaluationPeriod] = useState(1440);
  const [weightMethod, setWeightMethod] = useState("score_based");
  const [compositionThreshold, setCompositionThreshold] = useState(0.5);
  const [eliminationRule, setEliminationRule] = useState({
    min_score_threshold: 40.0,
    elimination_ratio: 0.2,
    min_consecutive_low: 3,
    low_score_threshold: 30.0,
    min_strategies: 2,
  });
  const [revivalRule, setRevivalRule] = useState({
    revival_score_threshold: 45,
    min_consecutive_high: 2,
    max_revival_per_round: 2,
  });
  const [perStrategyCapital, setPerStrategyCapital] = useState<number | undefined>(undefined);
  // 标记 evaluation_period 是否被手动修改过
  const [isEvalPeriodManual, setIsEvalPeriodManual] = useState(false);

  // Dynamic Selection History Data (shared between EliminationHistory and WeightEvolutionChart)
  const [dynamicSelectionHistory, setDynamicSelectionHistory] = useState<DynamicSelectionHistoryRecord[]>([]);

  // ─── Hydration-safe state ────────────────────────────────────────────────────
  // Use isMounted to prevent hydration mismatch for state restored from localStorage
  const [isMounted, setIsMounted] = useState(false);useEffect(() => {setIsMounted(true);
  }, []);

  // ─── Session Sync from Store ────────────────────────────────────────────────
  // Sync store state to local state for form controls
  // Guard: if store contains a FastAPI error object instead of valid session/status, treat as null
  const safeSession = (storeState.session && typeof storeState.session === 'object' && 'replay_session_id' in storeState.session)
    ? storeState.session : null;
  const safeStatus = (storeState.status && typeof storeState.status === 'object' && 'status' in storeState.status)
    ? storeState.status : null;
  const session = safeSession;
  const status = safeStatus;
  const isPolling = storeState.isPolling;
  // Only consider running if mounted AND polling is active
  const running = isMounted && isPolling && storeState.status?.status === "running";

  // When store session changes, sync local config state
  useEffect(() => {
    if (storeState.session && storeState.session.replay_session_id) {
      // Only sync if user hasn't manually changed these (check if session_id matches)
      if (urlSessionId === storeState.session.replay_session_id) {
        setSymbol(storeState.session.symbol);
        setSpeed(storeState.session.speed);
        setDateRange({
          start: storeState.session.start_time,
          end: storeState.session.end_time
        });
        if (storeState.session.strategy_type) {
          setSelectedType(storeState.session.strategy_type);
        }
        if (storeState.session.interval) {
          setInterval(storeState.session.interval);
        }
        if (storeState.session.params) {
          if (storeState.session.strategy_type === "dynamic_selection") {
            const p = storeState.session.params;
            if (p.atomic_strategies) setAtomicStrategies(p.atomic_strategies);
            if (p.evaluation_period) setEvaluationPeriod(p.evaluation_period);
            if (p.weight_method) setWeightMethod(p.weight_method);
            if (p.composition_threshold) setCompositionThreshold(p.composition_threshold);
            if (p.elimination_rule) setEliminationRule(p.elimination_rule);
            if (p.per_strategy_capital !== undefined) setPerStrategyCapital(p.per_strategy_capital);
          } else {
            setParamValues(storeState.session.params);
          }
        }
      }
    }
  }, [storeState.session, urlSessionId]);

  // Calculate progress hover info
  const calculateProgressHover = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    if (!session) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const percent = Math.max(0, Math.min(1, x / rect.width));
    
    const start = new Date(session.start_time).getTime();
    const end = new Date(session.end_time).getTime();
    const hoverTimeMs = start + (end - start) * percent;
    const hoverTimeStr = format(new Date(hoverTimeMs), "yyyy-MM-dd HH:mm");
    setHoverProgress({ x, time: hoverTimeStr, percent });
  }, [session]);

  // Handle drag on progress bar
  const handleDragStart = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    if (status?.status !== "paused") return;e.preventDefault();setIsDragging(true);calculateProgressHover(e);
  }, [status?.status, calculateProgressHover]);

  const handleDragMove = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    if (!isDragging) return;calculateProgressHover(e);
  }, [isDragging, calculateProgressHover]);

  const handleDragEnd = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    if (!isDragging || !session) {setIsDragging(false);
      return;
    }

    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const percent = Math.max(0, Math.min(1, x / rect.width));
    
    const start = new Date(session.start_time).getTime();
    const end = new Date(session.end_time).getTime();
    const targetTimeMs = start + (end - start) * percent;
    const targetDate = new Date(targetTimeMs);
    const targetTimeStr = format(targetDate, "HH:mm");
    setJumpDate(targetDate);setJumpTime(targetTimeStr);setShowJumpModal(true);setIsDragging(false);
  }, [isDragging, session]);

  // Quick jump from progress bar click (when paused)
  const handleProgressClick = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    if (status?.status !== "paused" || isDragging) return;
    
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const percent = Math.max(0, Math.min(1, x / rect.width));
    
    const start = new Date(session!.start_time).getTime();
    const end = new Date(session!.end_time).getTime();
    const targetTimeMs = start + (end - start) * percent;
    const targetDate = new Date(targetTimeMs);
    const targetTimeStr = format(targetDate, "HH:mm");
    setJumpDate(targetDate);setJumpTime(targetTimeStr);setShowJumpModal(true);
  }, [status?.status, session, isDragging]);

  // Helper to check if a date has data
  const isDateValid = useCallback((day: Date) => {
    if (!validDates || validDates.length === 0) return true;
    const dateStr = format(day, "yyyy-MM-dd");
    return validDates.includes(dateStr);
  }, [validDates]);

  // Apply preset profile
  const applyPreset = useCallback((preset: typeof PRESET_PROFILES[0]) => {
    if (!validDates || validDates.length === 0) return;
    
    const maxDate = new Date(validDates[validDates.length - 1]);
    const minDate = new Date(validDates[0]);
    
    // Calculate start date based on preset days
    const start = new Date(maxDate);
    start.setDate(start.getDate() - preset.config.days + 1);
    if (start < minDate) {
      start.setTime(minDate.getTime());
    }
    start.setHours(0, 0, 0, 0);
    
    const end = new Date(maxDate);
    end.setHours(23, 59, 59, 999);
    // 重置手动标记，允许自动计算新的 evaluation_period
    setIsEvalPeriodManual(false);
    setInterval(preset.config.interval);
    setSpeed(preset.config.speed);
    setDateRange({ start: start.toISOString(), end: end.toISOString() });
    setShowPresets(false);
    setToast({ message: `已应用「${preset.name}」配置`, type: "success" });
  }, [validDates]);

  // Auto-recommend interval when strategy changes
  useEffect(() => {
    const recommended = STRATEGY_INTERVAL_MAP[selectedType];
    if (recommended && interval !== recommended.interval) {
      // Only auto-change if user hasn't manually changed it yet
      if (!session) {
        setInterval(recommended.interval);
      }
    }
  }, [selectedType, session]);



  // 自动计算 evaluation_period
  useEffect(() => {
    // 如果用户手动修改过，不自动计算
    if (isEvalPeriodManual) return;
    
    // 只在 dynamic_selection 策略类型下自动计算
    if (selectedType !== "dynamic_selection") return;

    const intervalMinutes = INTERVAL_MINUTES[interval];
    if (!intervalMinutes) return;

    const startDate = new Date(dateRange.start);
    const endDate = new Date(dateRange.end);
    
    // 计算总分钟数
    const totalMinutes = (endDate.getTime() - startDate.getTime()) / (1000 * 60);
    if (totalMinutes <= 0) return;

    // 计算总 K 线数量
    const totalBars = Math.floor(totalMinutes / intervalMinutes);
    if (totalBars <= 0) return;

      // 目标是产生约 8 次评估（5~10 次的中间值）
    let recommendedPeriod = Math.round(totalBars / 8);
    
    // 上限：不超过总 K 线数量的 80%，确保至少能触发初始评估
    recommendedPeriod = Math.min(Math.floor(totalBars * 0.8), recommendedPeriod);
    
    // 下限：至少 50 根 K 线，避免评估过于频繁
    recommendedPeriod = Math.max(50, recommendedPeriod);

    setEvaluationPeriod(recommendedPeriod);
  }, [interval, dateRange.start, dateRange.end, selectedType, isEvalPeriodManual]);

  // Clear toast after 3s
  useEffect(() => {
    if (toast) {
      const timer = setTimeout(() => setToast(null), 3000);
      return () => clearTimeout(timer);
    }
  }, [toast]);

  // Show hint when replay is paused
  useEffect(() => {
    if (status?.status === "paused") {
      setShowProgressHint(true);
      const timer = setTimeout(() => setShowProgressHint(false), 3000);
      return () => clearTimeout(timer);
    }
  }, [status?.status]);

  // ─── Session Restoration on Mount & Visibility Change ────────────────────────
  useEffect(() => {
    // Restore session from URL on mount (deep link support)
    if (urlSessionId) {
      restoreStoreSession(urlSessionId);
    }
    // Note: Do NOT auto-restore from lastSessionId on mount to avoid confusing behavior.
    // Users should explicitly choose a session from the history list.
    // The visibility change handler is also disabled for auto-restore.

    const handleVisibilityChange = () => {
      // No auto-restore on visibility change either
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [urlSessionId, restoreStoreSession]);

  // ─── Sync URL with Session ────────────────────────────────────────────────────
  // When session is restored from localStorage, update the URL to include session_id
  useEffect(() => {
    if (storeState.session && storeState.session.replay_session_id) {
      const currentParams = new URLSearchParams(searchParams.toString());
      const currentSessionId = currentParams.get('session_id');
      
      // If URL doesn't have session_id but we have a restored session, update URL
      if (!currentSessionId && !urlSessionId) {
        const params = new URLSearchParams();params.set('session_id', storeState.session.replay_session_id);router.replace(`?${params.toString()}`, { scroll: false });
      }
    }
  }, [storeState.session, searchParams, router, urlSessionId]);

  // Fetch templates
  useEffect(() => {
    fetch("/api/v1/strategy/templates").then(r => r.json()).then(d => {
      const tpls = d.templates || [];setTemplates(tpls);
      if (tpls.length) {
        const first = tpls[0];setSelectedType(first.id);
        const defaults: Record<string, number> = {};first.params.forEach((p: any) => { defaults[p.key] = p.default; });setParamValues(defaults);
      }
    }).catch(() => {});
  }, []);

  // Update defaults when template changes
  useEffect(() => {
    const tpl = templates.find(t => t.id === selectedType);
    if (!tpl) return;
    const defaults: Record<string, number> = {};tpl.params.forEach(p => { defaults[p.key] = p.default; });setParamValues(defaults);
    
    // 根据策略类型推荐周期
    const recommended = STRATEGY_INTERVAL_MAP[selectedType];
    if (recommended) {
      // 策略类型切换时重置手动标记，允许自动计算新的 evaluation_period
      setIsEvalPeriodManual(false);
      setInterval(recommended.interval);
    }
  }, [selectedType, templates]);

  const currentTemplate = templates.find(t => t.id === selectedType);

  // Fetch valid date range when symbol OR interval changes
  useEffect(() => {
    if (!symbol) return;
    // Reset dateInitialized when symbol/interval changes to allow re-initialization
    setDateInitialized(false);
    fetch(`/api/v1/replay/valid-date-range/${symbol}?interval=${interval}`)
      .then(r => r.json())
      .then(d => {
        const dates = d.valid_dates || [];setValidDates(dates);
        
        // Auto-adjust date range when data changes
        if (dates.length > 0) {
          const maxValidDate = dates[dates.length - 1]; // Last date in list
          const minValidDate = dates[0]; // First date in list
          
          // Check if current date range is within new valid range
          const currentStart = new Date(dateRange.start);
          const currentEnd = new Date(dateRange.end);
          const minDate = new Date(minValidDate);
          const maxDate = new Date(maxValidDate);
          
          // If current range is completely outside valid range, reset to default
          const needsReset = currentEnd < minDate || currentStart > maxDate;
          
          if (needsReset) {
            // Calculate a sensible default: last 7 days within valid range
            const today = new Date(maxValidDate);
            let defaultEnd = new Date(today);
            defaultEnd.setHours(23, 59, 59, 999);
            
            let defaultStart = new Date(today);
            defaultStart.setDate(defaultStart.getDate() - 6);
            defaultStart.setHours(0, 0, 0, 0);
            
            // If range would be before min valid date, adjust
            if (defaultStart < minDate) {
              defaultStart = new Date(minValidDate);
            }
            // 日期范围重置时，允许自动计算新的 evaluation_period
            setIsEvalPeriodManual(false);
            setDateRange({
              start: defaultStart.toISOString(),
              end: defaultEnd.toISOString()
            });
          }
          setDateInitialized(true);
        }
      })
      .catch(() => {});
  }, [symbol, interval]);  // Now re-fetches when interval changes

  // Auto-adjust date range when interval changes and current range is out of bounds
  useEffect(() => {
    if (!validDates || validDates.length === 0 || !dateInitialized) return;
    
    const minValidDate = validDates[0];
    const maxValidDate = validDates[validDates.length - 1];
    const currentStart = new Date(dateRange.start);
    const currentEnd = new Date(dateRange.end);
    
    let needsAdjust = false;
    let newStart = currentStart;
    let newEnd = currentEnd;
    
    // Check if current range is before min valid date
    if (currentStart < new Date(minValidDate)) {
      newStart = new Date(minValidDate);
      needsAdjust = true;
    }
    
    // Check if current range is after max valid date
    if (currentEnd > new Date(maxValidDate)) {
      newEnd = new Date(maxValidDate);
      newEnd.setHours(23, 59, 59, 999);
      needsAdjust = true;
    }
    
    // Check if current range is completely out of valid dates
    if (currentEnd < new Date(minValidDate)) {
      newStart = new Date(minValidDate);
      newEnd = new Date(maxValidDate);
      newEnd.setHours(23, 59, 59, 999);
      needsAdjust = true;
    }
    
    if (needsAdjust) {
      // 日期范围自动调整时，允许自动计算新的 evaluation_period
      setIsEvalPeriodManual(false);
      setDateRange({
        start: newStart.toISOString(),
        end: newEnd.toISOString()
      });
    }
  }, [validDates]);

  // 后端时间估算 API 调用 - 当参数变化时获取服务端估算
  useEffect(() => {
    // 只在有有效日期并且没有活跃 session 时才估算
    if (!dateInitialized || !symbol || !interval || !selectedType || session) {
      return;
    }
    
    const fetchEstimate = async () => {
      setEstimateLoading(true);
      try {
        const res = await fetch('/api/v1/replay/estimate-time', {method: 'POST',headers: { 'Content-Type': 'application/json' },body: JSON.stringify({symbol,interval,start_time: dateRange.start,end_time: dateRange.end,speed,strategy_type: selectedType,
          }),
        });
        
        if (res.ok) {
          const data: EstimateTimeResponse = await res.json();
          setServerEstimate(data);
        } else {
          // API 失败时清除估算，使用前端 fallback
          setServerEstimate(null);
        }
      } catch (e) {
        console.warn('Failed to fetch time estimate:', e);
        setServerEstimate(null);
      } finally {
        setEstimateLoading(false);
      }
    };
    
    // 防抖：等待用户停止调整参数后再请求
    const debounceTimer = setTimeout(fetchEstimate, 500);
    return () => clearTimeout(debounceTimer);
  }, [symbol, interval, dateRange.start, dateRange.end, speed, selectedType, dateInitialized, session]);

  // Auto-save params when starting replay (sync to backtest page)
  const autoSaveParams = async (strategyType: string, params: Record<string, number>) => {
    try {
      await fetch(`/api/v1/strategy/templates/${strategyType}/params`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          params,
          updated_by: "manual_replay"
        }),
      });
      // Also refresh templates to reflect new defaults
      fetch("/api/v1/strategy/templates")
        .then(r => r.json())
        .then(d => {
          const tpls = d.templates || [];
          setTemplates(tpls);
        })
        .catch(() => {});
    } catch (e) {
      console.error("Failed to auto-save params:", e);
    }
  };

  const handleCreateAndStart = async () => {
    setError(null);
    try {
      // Validation for dynamic_selection strategy
      if (selectedType === "dynamic_selection") {
        if (atomicStrategies.length < 2) {
          setToast({ message: "动态选择策略需要至少 2 个原子策略", type: "error" });
          return;
        }
        // Check for duplicate strategy IDs
        const ids = atomicStrategies.map((s) => s.strategy_id);
        const duplicates = ids.filter((item, index) => ids.indexOf(item) !== index);
        if (duplicates.length > 0) {
          setToast({ message: `存在重复的策略 ID: ${[...new Set(duplicates)].join(", ")}`, type: "error" });
          return;
        }
        // Validate compositionThreshold range (0-1)
        if (compositionThreshold < 0 || compositionThreshold > 1) {
          setToast({ message: "组合阈值必须在 0 到 1 之间", type: "error" });
          return;
        }
        // Validate atomic strategy params against templates
        for (const strategy of atomicStrategies) {
          const template = templates.find(t => t.id === strategy.strategy_type);
          if (!template) {
            setToast({ message: `策略类型 ${strategy.strategy_type} 未找到模板`, type: "error" });
            return;
          }
          // Ensure params is not empty
          if (!strategy.params || Object.keys(strategy.params).length === 0) {
            setToast({ message: `策略 ${strategy.strategy_id} 的参数不能为空`, type: "error" });
            return;
          }
          // Validate each param against min/max
          for (const paramDef of template.params) {
            const value = strategy.params[paramDef.key];
            if (typeof value !== 'number') {
              setToast({ message: `策略 ${strategy.strategy_id} 的参数 ${paramDef.key} 无效`, type: "error" });
              return;
            }
            if (value < paramDef.min || value > paramDef.max) {
              setToast({ message: `策略 ${strategy.strategy_id} 的参数 ${paramDef.label} 超出范围 (${paramDef.min}-${paramDef.max})`, type: "error" });
              return;
            }
          }
        }
      }

      // 1. Create session
      // Build request body based on strategy type
      const requestBody: Record<string, any> = {
        strategy_id: 1,
        symbol,
        interval,
        start_time: dateRange.start,
        end_time: dateRange.end,
        speed,
        initial_capital: initialCapital,
        strategy_type: selectedType,
      };
      
      // Build params based on strategy type
      if (selectedType === "dynamic_selection") {
        // For dynamic_selection, use atomic_strategies from AtomicStrategyPanel
        requestBody.params = {
          atomic_strategies: atomicStrategies,
          evaluation_period: evaluationPeriod,
          weight_method: weightMethod,
          composition_threshold: compositionThreshold,
          elimination_rule: eliminationRule,
          revival_rule: revivalRule,
          ...(perStrategyCapital ? { per_strategy_capital: perStrategyCapital } : {}),
        };
      } else {
        requestBody.params = paramValues;
      }
      
      const createRes = await fetch("/api/v1/replay/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestBody),
      });
      const createData = await createRes.json();
      if (!createRes.ok) throw new Error(createData.detail || "创建回放失败");

      // Validate replay_session_id from response
      if (!createData.replay_session_id) {
        throw new Error("后端未返回有效的 replay_session_id");
      }

      const sessionId = createData.replay_session_id;
      
      // Update URL
      const params = new URLSearchParams(searchParams.toString());
      params.set("session_id", sessionId);
      router.push(`?${params.toString()}`);

      // 2. Start session
      const startRes = await fetch(`/api/v1/replay/${sessionId}/start`, { method: "POST" });
      const startData = await startRes.json();
      if (!startRes.ok) throw new Error(startData.detail || "启动回放失败");

      // 3. Update global store with full session info
      const newSession = {
        replay_session_id: sessionId,
        strategy_id: 1,
        symbol,
        start_time: dateRange.start,
        end_time: dateRange.end,
        speed,
        initial_capital: initialCapital,
        strategy_type: selectedType,
        interval,
        params: requestBody.params,
        status: "running" as const,
        created_at: new Date().toISOString()
      };
      setStoreSession(newSession);
      
      // 4. Start polling via global store
      startStorePolling(sessionId);
      
      // 5. Auto-save params to database for sync with backtest page
      if (selectedType !== "dynamic_selection") {
        autoSaveParams(selectedType, paramValues);
      }
    } catch (e: any) {
      setError(e.message || "网络错误");
    }
  };

  const handlePause = async () => {
    if (!session) return;
    try {
      const res = await fetch(`/api/v1/replay/${session.replay_session_id}/pause`, { method: "POST" });
      if (res.ok) {
        // Update store status directly
        setStoreStatus({
          ...(storeState.status || {}),
          status: "paused"
        } as ReplayStatus);
        // Also update session status in store
        if (storeState.session) {
          setStoreSession({ ...storeState.session, status: "paused" });
        }
        setToast({ message: "回放已暂停", type: "info" });
      } else {
        const data = await res.json().catch(() => ({}));
        setToast({ message: safeMsg(data.detail, "暂停失败"), type: "error" });
      }
    } catch (e) {
      setToast({ message: "网络错误，暂停失败", type: "error" });
    }
  };

  const handleResume = async () => {
    if (!session) return;
    try {
      const res = await fetch(`/api/v1/replay/${session.replay_session_id}/start`, { method: "POST" });
      if (res.ok) {
        // Update store status directly
        setStoreStatus({
          ...(storeState.status || {}),
          status: "running"
        } as ReplayStatus);
        // Also update session status in store
        if (storeState.session) {
          setStoreSession({ ...storeState.session, status: "running" });
        }
        // Resume polling
        startStorePolling(session.replay_session_id);
        setToast({ message: "回放已继续", type: "success" });
      } else {
        const data = await res.json().catch(() => ({}));
        setToast({ message: safeMsg(data.detail, "继续失败"), type: "error" });
      }
    } catch (e) {
      setToast({ message: "网络错误，继续失败", type: "error" });
    }
  };

  const handleJump = async () => {
    if (!session || !jumpDate) return;
    
    // Combine date and time
    const [hours, minutes] = jumpTime.split(':').map(Number);
    const targetDate = new Date(jumpDate);
    targetDate.setHours(hours, minutes, 0, 0);
    const targetIso = targetDate.toISOString();
    try {
      const res = await fetch(`/api/v1/replay/${session.replay_session_id}/jump`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target_timestamp: targetIso }),
      });
      if (res.ok) {
        setShowJumpModal(false);
        // After jump, stay paused - update global store
        if (storeState.status) {
          setStoreStatus({
            ...storeState.status,
            status: "paused",
            current_simulated_time: targetIso
          });
        }
        if (storeState.session) {
          setStoreSession({ ...storeState.session, status: "paused" });
        }
        setToast({ message: "已跳转到指定时间，回放已暂停", type: "success" });
      } else {
        const data = await res.json();
        setToast({ message: safeMsg(data.detail, "跳转失败：该时间点可能无行情数据"), type: "error" });
      }
    } catch (e) {
      setToast({ message: "网络错误，跳转失败", type: "error" });
    }
  };

  // Fetch history list - 使用增强的 sessions API
  const fetchHistory = useCallback(async (page: number = 1, resetPage: boolean = false) => {
    setHistoryLoading(true);
    try {
      const params = new URLSearchParams();
      params.set('page', String(resetPage ? 1 : page));
      params.set('page_size', '20');
      params.set('sort_by', 'created_at');
      params.set('sort_order', 'desc');
      
      if (showSavedOnly) {
        params.set('saved_only', 'true');
      }
      if (statusFilter && statusFilter !== 'all') {
        params.set('status', statusFilter);
      }
      if (strategyFilter && strategyFilter !== 'all') {
        params.set('strategy_type', strategyFilter);
      }
      
      const res = await fetch(`/api/v1/replay/sessions?${params.toString()}`);
      if (res.ok) {
        const data: SessionsResponse = await res.json();
        // 处理新的响应格式
        if (data.sessions) {
          setHistoryList(data.sessions);
          setHistoryPage(data.page);
          setHistoryTotalPages(data.total_pages);
          setHistoryTotalCount(data.total_count);
        } else {
          // 兼容旧版 API：如果直接返回数组
          setHistoryList(data as unknown as ReplayHistoryItem[]);
        }
      } else {
        const errorData = await res.json();
        setToast({ message: safeMsg(errorData.detail, "加载历史记录失败"), type: "error" });
      }
    } catch (e) {
      console.error("Failed to fetch history:", e);
      setToast({ message: "网络错误，无法加载历史记录", type: "error" });
    } finally {
      setHistoryLoading(false);
    }
  }, [showSavedOnly, statusFilter, strategyFilter]);

  // Fetch session stats
  const fetchSessionStats = useCallback(async (sessionId: string) => {
    setLoadingStatsId(sessionId);
    try {
      const res = await fetch(`/api/v1/replay/${sessionId}/stats`);
      if (res.ok) {
        const data = await res.json();
        setSessionStats(prev => ({ ...prev, [sessionId]: data }));
      } else {
        // 会话可能没有交易数据，这不是错误
        console.warn(`No stats for session ${sessionId}`);
      }
    } catch (e) {
      console.error("Failed to fetch session stats:", e);
      // 统计加载失败不弹 toast，因为可能是正常的（无交易数据）
    } finally {
      setLoadingStatsId(null);
    }
  }, []);

  // ─── Helper: Deduplicate equity curve by time field ─────────────────────────
  const deduplicateEquityCurve = useCallback((data: { t: string; v: number }[]): { t: string; v: number }[] => {
    if (!data || data.length === 0) return [];
    const map = new Map<string, { t: string; v: number }>();
    for (const item of data) {
      if (item.t) map.set(item.t, item);
    }
    return Array.from(map.values()).sort(
      (a, b) => new Date(a.t).getTime() - new Date(b.t).getTime()
    );
  }, []);

  // ─── Helper: Deduplicate trades by time+side+price ─────────────────────────
  const deduplicateTrades = useCallback((trades: any[]): any[] => {
    if (!trades || trades.length === 0) return [];
    const map = new Map<string, typeof trades[0]>();
    for (const trade of trades) {
      // Use time+side+price as unique key to avoid duplicate trades
      const key = `${trade.time}-${trade.side}-${trade.price}`;map.set(key, trade);
    }
    return Array.from(map.values()).sort(
      (a, b) => new Date(a.time).getTime() - new Date(b.time).getTime()
    );
  }, []);

  // Fetch all replay data (klines, equity, trades, position) in parallel
  const fetchReplayData = useCallback(async (sessionId: string) => {
    if (!sessionId) return;
    try {
      const [klineRes, equityRes, tradesRes, positionRes] = await Promise.all([fetch(`/api/v1/replay/${sessionId}/klines`)
          .then(async r => {
            if (!r.ok) { console.error(`[klines] HTTP ${r.status}:`, await r.text().catch(() => '')); return null; }
            return r.json();
          })
          .catch(e => { console.error('[klines] error:', e); return null; }),fetch(`/api/v1/replay/${sessionId}/equity-curve`)
          .then(async r => {
            if (!r.ok) { console.error(`[equity-curve] HTTP ${r.status}:`, await r.text().catch(() => '')); return null; }
            return r.json();
          })
          .catch(e => { console.error('[equity-curve] error:', e); return null; }),fetch(`/api/v1/replay/${sessionId}/trades`)
          .then(async r => {
            if (!r.ok) { console.error(`[trades] HTTP ${r.status}:`, await r.text().catch(() => '')); return null; }
            return r.json();
          })
          .catch(e => { console.error('[trades] error:', e); return null; }),fetch(`/api/v1/replay/${sessionId}/position`)
          .then(async r => {
            if (!r.ok) { console.error(`[position] HTTP ${r.status}:`, await r.text().catch(() => '')); return null; }
            return r.json();
          })
          .catch(e => { console.error('[position] error:', e); return null; }),
      ]);
      
      if (klineRes) {
        // Dedupe klines at source - remove duplicate timestamps, keep last occurrence
        const rawKlines = klineRes.klines || [];
        const klineMap = new Map<string, typeof rawKlines[0]>();
        for (const k of rawKlines) {
          klineMap.set(k.time, k);
        }
        const dedupedKlines = Array.from(klineMap.values()).sort(
          (a, b) => new Date(a.time).getTime() - new Date(b.time).getTime()
        );
        setKlineData(dedupedKlines);
        setIndicatorData(klineRes.indicators || {});
      }
      if (equityRes) {
        // Dedupe equity curve data by time
        const rawEquityCurve = equityRes.equity_curve || [];
        const dedupedEquityCurve = deduplicateEquityCurve(rawEquityCurve);
        setEquityCurveData(dedupedEquityCurve);
        
        // Dedupe markers by time (keep last for each timestamp)
        const rawMarkers = equityRes.markers || [];
        const dedupedMarkers = deduplicateTrades(rawMarkers);
        setTradeMarkers(dedupedMarkers);
        
        // Dedupe baseline curve
        const rawBaseline = equityRes.baseline_curve || [];
        const dedupedBaseline = deduplicateEquityCurve(rawBaseline);
        setBaselineCurveData(dedupedBaseline);
      }
      if (tradesRes) {
        // Dedupe trades to avoid duplicate entries
        const rawTrades = tradesRes.trades || [];
        const dedupedTrades = deduplicateTrades(rawTrades);
        setTradeList(dedupedTrades);
      }
      if (positionRes) {
        setPositionInfo(positionRes);
      } else {
        // 如果获取失败，显示空仓而不是骨架屏
        setPositionInfo({ has_position: false, side: "", quantity: 0, avg_price: 0, current_price: 0, unrealized_pnl: 0, unrealized_pnl_pct: 0 });
      }
    } catch (err) {
      console.error("Failed to fetch replay data:", err);
      // 保持上一次有效数据，不清空状态
    }
  }, [deduplicateEquityCurve, deduplicateTrades]);

  // Fetch equity curve when session changes
  useEffect(() => {
    if (session?.replay_session_id) {
      fetchReplayData(session.replay_session_id);
    } else {
      // Clear all chart data when no session
      setEquityCurveData([]);
      setBaselineCurveData([]);
      setTradeMarkers([]);
      setKlineData([]);
      setIndicatorData({});
      setTradeList([]);
      setPositionInfo(null);
    }
  }, [session?.replay_session_id, fetchReplayData]);

  // Refresh all replay data periodically when running
  useEffect(() => {
    if (status?.status === "running" && session?.replay_session_id) {
      const intervalId = window.setInterval(() => {
        fetchReplayData(session.replay_session_id);
      }, 5000); // Refresh every 5 seconds while running
      return () => window.clearInterval(intervalId);
    }
    // Fetch once when status changes to completed
    if (status?.status === "completed" && session?.replay_session_id) {
      fetchReplayData(session.replay_session_id);
    }
  }, [status?.status, session?.replay_session_id, fetchReplayData]);

  // Toggle history panel
  const toggleHistoryPanel = useCallback(() => {
    if (!showHistoryPanel) {
      fetchHistory(1, true);
    }
    setShowHistoryPanel(!showHistoryPanel);
  }, [showHistoryPanel, fetchHistory]);

  // 当筛选条件改变时重新获取
  useEffect(() => {
    if (showHistoryPanel) {
      fetchHistory(1, true);
    }
  }, [showSavedOnly, statusFilter, strategyFilter]);

  // Shared polling for Dynamic Selection History (used by EliminationHistory and WeightEvolutionChart)
  // This consolidates two separate 5s polling requests into one, reducing network overhead
  useEffect(() => {
    const abortController = new AbortController();

    const fetchDynamicSelectionHistory = async (isPolling = false) => {
      const sessionId = safeSession?.replay_session_id;
      const strategyType = safeSession?.strategy_type;
      
      // Debug: log session info
      console.log('[DynamicSelectionHistory] fetchDynamicSelectionHistory called:', {
        isPolling,
        sessionId,
        strategyType,
        running,
        hasSession: !!safeSession,
      });
      
      if (!sessionId) {
        console.warn('[DynamicSelectionHistory] No sessionId available, skipping fetch');
        if (!isPolling) setDynamicSelectionHistory([]);
        return;
      }
      
      // Only fetch for dynamic_selection strategy type
      if (strategyType !== 'dynamic_selection') {
        console.log('[DynamicSelectionHistory] Strategy type is not dynamic_selection, skipping fetch');
        return;
      }

      try {
        const res = await fetch(
          `/api/v1/dynamic-selection/history?session_id=${sessionId}&limit=100`,
          { signal: abortController.signal }
        );
        if (!res.ok) {
          console.warn(`获取动态选择历史失败：服务器返回 ${res.status}`);
          if (!isPolling) setDynamicSelectionHistory([]);
          return;
        }
        const data = await res.json();
        console.log('[DynamicSelectionHistory] Fetched data:', {
          recordCount: Array.isArray(data) ? data.length : 0,
          isArray: Array.isArray(data),
        });
        if (Array.isArray(data)) {
          setDynamicSelectionHistory(data);
        } else {
          console.warn("DynamicSelectionHistory: API返回非数组类型", typeof data);
          setDynamicSelectionHistory([]);
        }
      } catch (err: any) {
        // Ignore abort errors
        if (err.name === 'AbortError') return;
        console.warn("获取动态选择历史失败:", err);
        if (!isPolling) setDynamicSelectionHistory([]);
      }
    };

    fetchDynamicSelectionHistory();
    
    let intervalId: number | null = null;
    // Only poll when running AND strategy_type is dynamic_selection
    const shouldPoll = running && safeSession?.strategy_type === 'dynamic_selection' && safeSession?.replay_session_id;
    console.log('[DynamicSelectionHistory] Polling setup:', { shouldPoll, running, strategyType: safeSession?.strategy_type });
    if (shouldPoll) {
      intervalId = window.setInterval(() => fetchDynamicSelectionHistory(true), 5000);
    }
    
    return () => {
      abortController.abort();
      if (intervalId) window.clearInterval(intervalId);
    };
  }, [safeSession?.replay_session_id, safeSession?.strategy_type, running]);

  // Toggle save status
  const handleToggleSave = async (replaySessionId: string) => {
    try {
      const res = await fetch(`/api/v1/replay/${replaySessionId}/save`, { method: "PATCH" });
      if (res.ok) {
        // Update local state
        setHistoryList(prev => prev.map(item =>
          item.replay_session_id === replaySessionId
            ? { ...item, is_saved: !item.is_saved }
            : item
        ));
        // If current session, update its state in global store
        if (session?.replay_session_id === replaySessionId && storeState.session) {
          setStoreSession({ ...storeState.session, is_saved: !storeState.session.is_saved });
        }
        const data = await res.json();
        setToast({ message: safeMsg(data.message, "状态已更新"), type: "success" });
      } else {
        const data = await res.json();
        setToast({ message: safeMsg(data.detail, "保存失败"), type: "error" });
      }
    } catch (e) {
      setToast({ message: "网络错误", type: "error" });
    }
  };

  // Delete session
  const handleDeleteSession = async (replaySessionId: string) => {
    if (!confirm("确定要删除这条回放记录吗？此操作不可撤销。")) return;
    try {
      const res = await fetch(`/api/v1/replay/${replaySessionId}`, { method: "DELETE" });
      if (res.ok) {
        // Remove from local state
        setHistoryList(prev => prev.filter(item => item.replay_session_id !== replaySessionId));
        // Clear current session if it was deleted - use global store
        if (session?.replay_session_id === replaySessionId) {
          clearStoreSession();
          // Clear URL param
          const params = new URLSearchParams(searchParams.toString());
          params.delete("session_id");
          router.push(`?${params.toString()}`);
        }
        setToast({ message: "记录已删除", type: "success" });
      } else {
        const data = await res.json();
        setToast({ message: safeMsg(data.detail, "删除失败"), type: "error" });
      }
    } catch (e) {
      setToast({ message: "网络错误", type: "error" });
    }
  };

  // 快速对比回测：从 replay session 提取参数，自动运行回测，然后跳转到 analytics 对比
  const handleQuickBacktest = async (targetSessionId?: string) => {
    const sessionId = targetSessionId || session?.replay_session_id;
    if (!sessionId) return;
    
    // 设置加载状态
    if (targetSessionId) {
      setHistoryQuickBacktestId(targetSessionId);
    } else {
      setQuickBacktestLoading(true);
    }
    try {
      // 使用新的 API 端点
      const res = await fetch(`/api/v1/replay/${sessionId}/quick-backtest`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      const data = await res.json();
      if (!res.ok) {
        const detail = data?.detail;
        const msg = typeof detail === 'string' ? detail : JSON.stringify(detail) || "回测失败";
        setToast({ message: msg, type: "error" });
        return;
      }
      
      // 显示成功提示
      setToast({ message: "对比回测完成，正在跳转...", type: "success" });
      
      // 跳转到 analytics 页面的对比 Tab，带上参数
      setTimeout(() => {
        router.push(`/analytics?tab=comparison&rb_session=${sessionId}&backtest_id=${data.backtest_id}`);
      }, 500);
    } catch (e: any) {
      setToast({ message: String(e?.message || e || "网络错误，无法运行回测"), type: "error" });
    } finally {
      if (targetSessionId) {
        setHistoryQuickBacktestId(null);
      } else {
        setQuickBacktestLoading(false);
      }
    }
  };

  return (
    <div className="min-h-screen bg-slate-950">
      {/* Header */}
      <header className="border-b border-slate-800 bg-slate-900/50 backdrop-blur-sm sticky top-0 z-40">
        <div className="container mx-auto px-4 py-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-xl flex items-center justify-center">
                <History className="w-5 h-5 text-white" />
              </div>
              <div>
                <h1 className="text-lg font-bold text-slate-100">QuantAgent OS</h1>
                <p className="text-[10px] text-slate-400">历史回放模拟</p>
              </div>
            </div>
            <nav className="hidden md:flex items-center gap-1">
              <Link href="/dashboard" className="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-100 hover:bg-slate-800 rounded-lg transition-all flex items-center gap-1.5">
                <LayoutDashboard className="w-4 h-4" /> 仪表盘
              </Link>
              <Link href="/backtest" className="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-100 hover:bg-slate-800 rounded-lg transition-all flex items-center gap-1.5">
                <BarChart2 className="w-4 h-4" /> 回测
              </Link>
              <span className="px-3 py-1.5 text-sm text-indigo-400 bg-indigo-500/10 rounded-lg border border-indigo-500/20 font-medium flex items-center gap-1.5">
                <History className="w-4 h-4" /> 历史回放
              </span>
              <Link href="/terminal" className="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-100 hover:bg-slate-800 rounded-lg transition-all flex items-center gap-1.5">
                <Terminal className="w-4 h-4" /> 终端
              </Link>
              <button onClick={toggleHistoryPanel}
                className={`px-3 py-1.5 text-sm rounded-lg transition-all flex items-center gap-1.5 ${showHistoryPanel
                    ? 'text-amber-400 bg-amber-500/10 border border-amber-500/20' 
                    : 'text-slate-400 hover:text-slate-100 hover:bg-slate-800'
                }`}
              >
                <List className="w-4 h-4" /> 历史记录
              </button>
            </nav>
          </div>
        </div>
      </header>

      <main className="container mx-auto px-4 py-6">
        {/* ── History Panel ── */}
        {showHistoryPanel && (
          <Card className="bg-slate-900 border-slate-700/50 shadow-lg mb-6">
            <CardHeader className="pb-3 border-b border-slate-800/50 flex flex-row items-center justify-between">
              <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
                <List className="w-4 h-4 text-amber-400" />
                回放历史记录
                <Badge variant="outline" className="ml-2 text-xs border-slate-600 text-slate-400">
                  {historyTotalCount > 0 ? `${historyTotalCount} 条` : `${historyList.length} 条`}
                </Badge>
              </CardTitle>
              <div className="flex items-center gap-2">
                {/* 状态筛选 */}
                <Select value={statusFilter} onValueChange={setStatusFilter}>
                  <SelectTrigger className="w-[100px] h-7 bg-slate-800 border-slate-700 text-slate-300 text-xs">
                    <SelectValue placeholder="状态" />
                  </SelectTrigger>
                  <SelectContent className="bg-slate-800 border-slate-700">
                    <SelectItem value="all" className="text-slate-100 text-xs focus:bg-slate-700">全部状态</SelectItem>
                    <SelectItem value="completed" className="text-slate-100 text-xs focus:bg-slate-700">已完成</SelectItem>
                    <SelectItem value="running" className="text-slate-100 text-xs focus:bg-slate-700">运行中</SelectItem>
                    <SelectItem value="paused" className="text-slate-100 text-xs focus:bg-slate-700">已暂停</SelectItem>
                    <SelectItem value="failed" className="text-slate-100 text-xs focus:bg-slate-700">失败</SelectItem>
                  </SelectContent>
                </Select>
                {/* 策略筛选 */}
                <Select value={strategyFilter} onValueChange={setStrategyFilter}>
                  <SelectTrigger className="w-[90px] h-7 bg-slate-800 border-slate-700 text-slate-300 text-xs">
                    <SelectValue placeholder="策略" />
                  </SelectTrigger>
                  <SelectContent className="bg-slate-800 border-slate-700">
                    <SelectItem value="all" className="text-slate-100 text-xs focus:bg-slate-700">全部策略</SelectItem>
                    {templates.map(t => (
                      <SelectItem key={t.id} value={t.id} className="text-slate-100 text-xs focus:bg-slate-700">{t.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <button onClick={() => { setShowSavedOnly(!showSavedOnly); }}
                  className={`px-3 py-1 text-xs rounded-lg transition-all flex items-center gap-1.5 ${showSavedOnly
                      ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30' 
                      : 'bg-slate-800 text-slate-400 border border-slate-700 hover:bg-slate-700'
                  }`}
                >
                  <BookmarkCheck className="w-3.5 h-3.5" />
                  已保存
                </button>
                <button onClick={() => fetchHistory(historyPage)}
                  className="p-1.5 rounded-lg bg-slate-800 text-slate-400 hover:bg-slate-700 hover:text-slate-200 transition-all"title="刷新"
                >
                  <RefreshCw className={`w-4 h-4 ${historyLoading ? 'animate-spin' : ''}`} />
                </button>
              </div>
            </CardHeader>
            <CardContent className="p-4">
              {historyLoading ? (
                <div className="flex items-center justify-center py-8 text-slate-500">
                  <RefreshCw className="w-5 h-5 animate-spin mr-2" /> 加载中...
                </div>
              ) : historyList.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-8 text-slate-500 space-y-2">
                  <History className="w-8 h-8 opacity-30" />
                  <p className="text-sm">{showSavedOnly ? "暂无保存的记录" : "暂无回放记录"}</p>
                </div>
              ) : (
                <div className="space-y-2 max-h-[500px] overflow-y-auto">
                  {historyList.map((item) => {
                    const isExpanded = expandedSessionId === item.replay_session_id;
                    const stats = sessionStats[item.replay_session_id];
                    const isLoadingStats = loadingStatsId === item.replay_session_id;
                    // 从 summary 获取赏率（如果有）
                    const summaryWinRate = item.summary?.win_rate;
                    
                    return (
                      <div key={item.replay_session_id} className="space-y-1">
                        <div 
                          className={`flex items-center justify-between p-3 rounded-lg border transition-all cursor-pointer ${session?.replay_session_id === item.replay_session_id
                              ? 'bg-indigo-500/10 border-indigo-500/30'
                              : 'bg-slate-800/50 border-slate-700/50 hover:bg-slate-800 hover:border-slate-600'
                          }`} onClick={() => {
                            if (isExpanded) {setExpandedSessionId(null);
                            } else {setExpandedSessionId(item.replay_session_id);
                              // Fetch stats if not already loaded
                              if (!sessionStats[item.replay_session_id]) {fetchSessionStats(item.replay_session_id);
                              }
                            }
                          }}
                        >
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-1">
                              <ChevronRight className={`w-4 h-4 text-slate-400 transition-transform ${isExpanded ? 'rotate-90' : ''}`} />
                              <span className="text-sm font-medium text-slate-100 truncate">
                                {item.symbol}
                              </span>
                              <Badge className={`text-[10px] px-1.5 py-0.5 ${item.status === 'completed' ? 'bg-green-500/10 text-green-400 border-green-500/20' :item.status === 'running' ? 'bg-blue-500/10 text-blue-400 border-blue-500/20' :item.status === 'failed' ? 'bg-red-500/10 text-red-400 border-red-500/20' :
                                'bg-slate-700 text-slate-400 border-slate-600'
                              }`}>
                                {item.status}
                              </Badge>
                              {item.is_saved && (
                                <Bookmark className="w-3.5 h-3.5 text-amber-400" />
                              )}
                            </div>
                            <div className="flex items-center gap-4 text-[11px] text-slate-500">
                              <span>{item.strategy_type?.toUpperCase() || 'MA'}</span>
                              <span>{format(new Date(item.start_time), "MM-dd HH:mm")} ~ {format(new Date(item.end_time), "MM-dd HH:mm")}</span>
                              {/* 显示 summary 信息（如果有） */}
                              {item.summary?.total_return !== null && item.summary?.total_return !== undefined ? (
                                <Badge className={`text-[10px] px-1.5 py-0 ${item.summary.total_return >= 0
                                    ? 'bg-green-500/10 text-green-400 border-green-500/20' 
                                    : 'bg-red-500/10 text-red-400 border-red-500/20'
                                }`}>
                                  {item.summary.total_return >= 0 ? '+' : ''}{item.summary.total_return.toFixed(2)}%
                                </Badge>
                              ) : item.pnl !== null && (
                                <span className={item.pnl >= 0 ? 'text-green-400' : 'text-red-400'}>
                                  {item.pnl >= 0 ? '+' : ''}{item.pnl.toFixed(2)}
                                </span>
                              )}
                              {/* 显示交易次数 */}
                              {item.summary?.trade_count !== null && item.summary?.trade_count !== undefined && (
                                <span className="text-slate-400">{item.summary.trade_count}笔</span>
                              )}
                            </div>
                          </div>
                          <div className="flex items-center gap-1 ml-4" onClick={(e) => e.stopPropagation()}>
                            {/* 快速对比回测按钮 - 仅已完成的会话 */}
                            {item.status === 'completed' && (
                              <button onClick={() => handleQuickBacktest(item.replay_session_id)} disabled={historyQuickBacktestId === item.replay_session_id}
                                className="p-1.5 rounded-lg bg-cyan-500/10 text-cyan-400 hover:bg-cyan-500/20 transition-all border border-cyan-500/20"title="快速对比回测"
                              >
                                {historyQuickBacktestId === item.replay_session_id ? (
                                  <RefreshCw className="w-4 h-4 animate-spin" />
                                ) : (
                                  <BarChart2 className="w-4 h-4" />
                                )}
                              </button>
                            )}
                            <button onClick={() => handleToggleSave(item.replay_session_id)}
                              className={`p-1.5 rounded-lg transition-all ${item.is_saved
                                  ? 'bg-amber-500/20 text-amber-400 hover:bg-amber-500/30'
                                  : 'bg-slate-700 text-slate-400 hover:bg-slate-600 hover:text-slate-200'
                              }`}title={item.is_saved ? "取消保存" : "保存记录"}
                            >
                              {item.is_saved ? <BookmarkCheck className="w-4 h-4" /> : <Bookmark className="w-4 h-4" />}
                            </button>
                            <button onClick={() => handleDeleteSession(item.replay_session_id)}
                              className="p-1.5 rounded-lg bg-slate-700 text-slate-400 hover:bg-red-500/20 hover:text-red-400 transition-all"title="删除记录"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </div>
                        </div>
                        
                        {/* Expanded Details Panel */}
                        {isExpanded && (
                          <div className="bg-slate-800/30 border border-slate-700/30 rounded-lg p-3 ml-4">
                            {isLoadingStats ? (
                              <div className="flex items-center justify-center py-4 text-slate-500">
                                <RefreshCw className="w-4 h-4 animate-spin mr-2" /> 加载统计数据...
                              </div>
                            ) : stats ? (
                              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
                                <div className="bg-slate-800/50 rounded p-2">
                                  <div className="text-slate-500 mb-1">交易次数</div>
                                  <div className="text-slate-100 font-medium">{stats.total_trades}</div>
                                </div>
                                <div className="bg-slate-800/50 rounded p-2">
                                  <div className="text-slate-500 mb-1">胜率</div>
                                  <div className={`font-medium ${stats.win_rate >= 50 ? 'text-green-400' : 'text-red-400'}`}>
                                    {stats.win_rate.toFixed(1)}%
                                  </div>
                                </div>
                                <div className="bg-slate-800/50 rounded p-2">
                                  <div className="text-slate-500 mb-1">总盈亏</div>
                                  <div className={`font-medium ${stats.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                    {stats.total_pnl >= 0 ? '+' : ''}{stats.total_pnl.toFixed(2)}
                                  </div>
                                </div>
                                <div className="bg-slate-800/50 rounded p-2">
                                  <div className="text-slate-500 mb-1">收益率</div>
                                  <div className={`font-medium ${stats.returns_pct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                    {stats.returns_pct >= 0 ? '+' : ''}{stats.returns_pct.toFixed(2)}%
                                  </div>
                                </div>
                                <div className="bg-slate-800/50 rounded p-2">
                                  <div className="text-slate-500 mb-1">盈利次数</div>
                                  <div className="text-green-400 font-medium">{stats.winning_trades}</div>
                                </div>
                                <div className="bg-slate-800/50 rounded p-2">
                                  <div className="text-slate-500 mb-1">亏损次数</div>
                                  <div className="text-red-400 font-medium">{stats.losing_trades}</div>
                                </div>
                                <div className="bg-slate-800/50 rounded p-2">
                                  <div className="text-slate-500 mb-1">平均盈利</div>
                                  <div className="text-green-400 font-medium">+{stats.avg_win.toFixed(2)}</div>
                                </div>
                                <div className="bg-slate-800/50 rounded p-2">
                                  <div className="text-slate-500 mb-1">平均亏损</div>
                                  <div className="text-red-400 font-medium">-{stats.avg_loss.toFixed(2)}</div>
                                </div>
                                <div className="bg-slate-800/50 rounded p-2">
                                  <div className="text-slate-500 mb-1">最大单笔盈利</div>
                                  <div className="text-green-400 font-medium">+{stats.max_profit.toFixed(2)}</div>
                                </div>
                                <div className="bg-slate-800/50 rounded p-2">
                                  <div className="text-slate-500 mb-1">最大单笔亏损</div>
                                  <div className="text-red-400 font-medium">-{stats.max_loss.toFixed(2)}</div>
                                </div>
                                <div className="bg-slate-800/50 rounded p-2">
                                  <div className="text-slate-500 mb-1">手续费</div>
                                  <div className="text-slate-400 font-medium">-{stats.total_fees.toFixed(2)}</div>
                                </div>
                                <div className="bg-slate-800/50 rounded p-2">
                                  <div className="text-slate-500 mb-1">最终权益</div>
                                  <div className="text-slate-100 font-medium">${stats.final_equity.toFixed(2)}</div>
                                </div>
                              </div>
                            ) : (
                              <div className="text-center py-4 text-slate-500 text-xs">
                                暂无交易数据
                              </div>
                            )}
                            
                            {/* Strategy Parameters */}
                            {item.params && Object.keys(item.params).length > 0 && (
                              <div className="mt-3 pt-3 border-t border-slate-700/30">
                                <div className="text-[10px] text-slate-500 mb-2">策略参数</div>
                                <div className="flex flex-wrap gap-1">
                                  {Object.entries(item.params).map(([key, value]) => (
                                    <Badge key={key} variant="outline" className="text-[10px] border-slate-600 text-slate-400 bg-slate-800/50">
                                      {key}: {String(value)}
                                    </Badge>
                                  ))}
                                </div>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
              
              {/* 分页控件 */}
              {historyTotalPages > 1 && (
                <div className="flex items-center justify-between mt-4 pt-4 border-t border-slate-700/30">
                  <div className="text-xs text-slate-500">
                    第 {historyPage} / {historyTotalPages} 页，共 {historyTotalCount} 条
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"size="sm"disabled={historyPage <= 1 || historyLoading} onClick={() => fetchHistory(historyPage - 1)}
                      className="h-7 px-2 text-xs border-slate-700 text-slate-300 hover:bg-slate-800"
                    >
                      <ChevronLeft className="w-4 h-4" />
                      上一页
                    </Button>
                    <Button
                      variant="outline"size="sm"disabled={historyPage >= historyTotalPages || historyLoading} onClick={() => fetchHistory(historyPage + 1)}
                      className="h-7 px-2 text-xs border-slate-700 text-slate-300 hover:bg-slate-800"
                    >
                      下一页
                      <ChevronRight className="w-4 h-4" />
                    </Button>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* ── Left: Config Panel ── */}
          <div className="lg:col-span-1 space-y-4">
            <Card className="bg-slate-900 border-slate-700/50 shadow-lg">
              <CardHeader className="pb-3 border-b border-slate-800/50">
                <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
                  <Settings2 className="w-4 h-4 text-indigo-400" />
                  回放配置
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4 pt-4">
                {/* Strategy Selection */}
                <div>
                  <label className="text-xs text-slate-400 mb-1.5 block">选择策略</label>
                  <Select value={selectedType} onValueChange={setSelectedType}>
                    <SelectTrigger className="w-full bg-slate-800 border-slate-700 text-slate-100 h-9 text-sm">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="bg-slate-800 border-slate-700">
                      {templates.map(t => (
                        <SelectItem key={t.id} value={t.id} className="text-slate-100 focus:bg-slate-700 cursor-pointer">{t.name}</SelectItem>
                      ))}
                      <SelectSeparator className="bg-slate-700" />
                      <SelectItem value="dynamic_selection" className="text-indigo-300 focus:bg-slate-700 cursor-pointer">
                        🔄 动态选择（多策略组合）
                      </SelectItem>
                    </SelectContent>
                  </Select>
                  {STRATEGY_INTERVAL_MAP[selectedType] && (
                    <p className="text-[10px] text-indigo-400/70 mt-1">
                      推荐周期: {STRATEGY_INTERVAL_MAP[selectedType].label}
                    </p>
                  )}
                </div>

                {/* Preset Profiles Toggle */}
                <div className="border border-slate-700/50 rounded-lg overflow-hidden">
                  <button onClick={() => setShowPresets(!showPresets)}
                    className="w-full px-3 py-2 bg-slate-800/50 hover:bg-slate-800 text-left flex items-center justify-between transition-all"
                  >
                    <span className="text-xs text-slate-300 flex items-center gap-2">
                      <Zap className="w-3.5 h-3.5 text-amber-400" />
                      快速预设方案
                    </span>
                    {showPresets ? <ChevronUp className="w-4 h-4 text-slate-400" /> : <ChevronDown className="w-4 h-4 text-slate-400" />}
                  </button>
                  
                  {showPresets && (
                    <div className="p-2 space-y-2 bg-slate-900/50">
                      {PRESET_PROFILES.map(preset => {
                        const days = (() => {
                          if (!validDates || validDates.length === 0) return preset.config.days;
                          const maxDate = new Date(validDates[validDates.length - 1]);
                          const minDate = new Date(validDates[0]);
                          const start = new Date(maxDate);start.setDate(start.getDate() - preset.config.days + 1);
                          if (start < minDate) return Math.ceil((maxDate.getTime() - minDate.getTime()) / 86400000) + 1;
                          return preset.config.days;
                        })();
                        const estimatedTime = calculateEstimatedTime(days, preset.config.interval, preset.config.speed);
                        const dataPoints = estimateDataPoints(days, preset.config.interval);
                        const dataPointsStr = dataPoints >= 1000 ? `约${(dataPoints / 1000).toFixed(0)}k根` : `${dataPoints}根`;
                        
                        return (
                          <button key={preset.id} onClick={() => applyPreset(preset)}
                            className="w-full p-2 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700/50 hover:border-indigo-500/30 transition-all text-left group"
                          >
                            <div className="flex items-start justify-between">
                              <div className="flex-1">
                                <div className="flex items-center gap-1.5">
                                  <span className="text-sm">{preset.icon}</span>
                                  <span className="text-xs font-medium text-slate-200 group-hover:text-indigo-300">{preset.name}</span>
                                </div>
                                <p className="text-[10px] text-slate-500 mt-0.5">{preset.desc}</p>
                              </div>
                              <div className="text-right">
                                <p className="text-[10px] text-amber-400/80">{estimatedTime}</p>
                                <p className="text-[10px] text-slate-500">{dataPointsStr}</p>
                              </div>
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>

                {/* Market Symbol */}
                <div>
                  <label className="text-xs text-slate-400 mb-1.5 block">交易品种</label>
                  <Select value={symbol} onValueChange={setSymbol}>
                    <SelectTrigger className="w-full bg-slate-800 border-slate-700 text-slate-100 h-9 text-sm">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="bg-slate-800 border-slate-700">
                      {SYMBOLS.map(s => (
                        <SelectItem key={s.value} value={s.value} className="text-slate-100 focus:bg-slate-700 cursor-pointer">{s.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                {/* Date Range Picker */}
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <label className="text-xs text-slate-400">回放日期范围</label>
                    {validDates && validDates.length > 0 && (
                      <span className="text-[10px] text-slate-500">
                        {(() => {
                          const minD = validDates[0];
                          const maxD = validDates[validDates.length - 1];
                          // Calculate actual days span from date difference, not array length
                          const minDate = new Date(minD);
                          const maxDate = new Date(maxD);
                          const daysDiff = Math.ceil((maxDate.getTime() - minDate.getTime()) / 86400000) + 1;
                          const intervalLabel = INTERVALS.find(i => i.value === interval)?.label || interval;
                          return `${intervalLabel}: ${minD} ~ ${maxD} (共${daysDiff}天)`;
                        })()}
                      </span>
                    )}
                  </div>
                  <DateRangePicker 
                    value={dateRange}
                    onChange={(newRange) => {
                      setIsEvalPeriodManual(false);
                      setDateRange(newRange);
                    }}
                    validDates={validDates}
                    quickRanges={generateQuickRanges(validDates, interval)}
                    minDate={validDates && validDates.length > 0 ? new Date(validDates[0]) : null}
                    maxDate={validDates && validDates.length > 0 ? new Date(validDates[validDates.length - 1]) : null}
                  />
                </div>

                {/* Interval */}
                <div>
                  <label className="text-xs text-slate-400 mb-1.5 block">K线周期</label>
                  <Select 
                    value={interval} 
                    onValueChange={(value) => {
                      setIsEvalPeriodManual(false);
                      setInterval(value);
                    }}
                  >
                    <SelectTrigger className="w-full bg-slate-800 border-slate-700 text-slate-100 h-9 text-sm">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="bg-slate-800 border-slate-700">
                      {INTERVALS.map(i => (
                        <SelectItem key={i.value} value={i.value} className="text-slate-100 focus:bg-slate-700 cursor-pointer">{i.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                {/* Estimated Time Display - 使用后端估算优先，前端 fallback */}
                {validDates && validDates.length > 0 && (() => {
                  const startDate = new Date(dateRange.start);
                  const endDate = new Date(dateRange.end);
                  const days = Math.max(1, Math.ceil((endDate.getTime() - startDate.getTime()) / 86400000));
                  
                  // 前端 fallback 计算
                  const fallbackDataPoints = estimateDataPoints(days, interval);
                  const fallbackEstimatedTime = calculateEstimatedTime(fallbackDataPoints, interval, speed);
                  
                  // 优先使用后端估算
                  const useServerEstimate = serverEstimate && !estimateLoading;
                  const dataPoints = useServerEstimate ? serverEstimate.bar_count : fallbackDataPoints;
                  const estimatedSeconds = useServerEstimate ? serverEstimate.estimated_seconds : 0;
                  const serverNotes = useServerEstimate ? serverEstimate.notes : null;
                  
                  // 格式化时间显示
                  const formatTime = (seconds: number) => {
                    if (speed === -1) return '极速完成';
                    if (seconds < 1) return '少于1秒';
                    if (seconds < 60) return `约 ${Math.round(seconds)} 秒`;
                    if (seconds < 3600) return `约 ${Math.round(seconds / 60)} 分钟`;
                    return `约 ${(seconds / 3600).toFixed(1)} 小时`;
                  };
                  
                  const estimatedTime = useServerEstimate ? formatTime(estimatedSeconds) : fallbackEstimatedTime;
                  const dataPointsStr = dataPoints >= 1000 ? `约${(dataPoints / 1000).toFixed(0)}k根K线` : `约${dataPoints}根K线`;
                  const hasNoData = dataPoints === 0;
                  
                  return (
                    <div className={`rounded-lg p-3 ${hasNoData ? 'bg-red-500/10 border border-red-500/30' : 'bg-slate-800/50 border border-amber-500/20'}`}>
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-[10px] text-slate-400 flex items-center gap-1">
                          <Clock className="w-3 h-3" />
                          预计回放时间
                          {estimateLoading && <RefreshCw className="w-3 h-3 animate-spin text-indigo-400" />}
                          {useServerEstimate && <span className="text-indigo-400/60">(服务端估算)</span>}
                        </span>
                        <Badge variant="outline" className="text-[10px] border-slate-600 text-slate-300 bg-slate-800">
                          {speed === -1 ? "极速" : `${speed}x`}
                        </Badge>
                      </div>
                      <div className="flex items-end justify-between">
                        <div>
                          <p className={`text-lg font-bold ${hasNoData ? 'text-red-400' : 'text-amber-400'}`}>
                            {estimateLoading ? '估算中...' : estimatedTime}
                          </p>
                          <p className="text-[10px] text-slate-500 mt-0.5">
                            {interval} · {days}天范围 · {dataPointsStr}
                          </p>
                          {hasNoData && (
                            <p className="text-[10px] text-red-400 mt-1 flex items-center gap-1">
                              <AlertTriangle className="w-3 h-3" />
                              日期超出有效数据范围
                            </p>
                          )}
                          {/* 后端返回的注释（如高倍速性能衰减提示） */}
                          {serverNotes && (
                            <p className="text-[10px] text-amber-400/70 mt-1 flex items-center gap-1">
                              <Info className="w-3 h-3" />
                              {serverNotes}
                            </p>
                          )}
                        </div>
                        {!hasNoData && speed !== -1 && speed < 500 && (
                          <button onClick={() => {
                              const recommendedSpeed = days <= 3 ? 1000 : days <= 7 ? 500 : 100;setSpeed(recommendedSpeed);
                            }}
                            className="text-[10px] text-indigo-400 hover:text-indigo-300 flex items-center gap-0.5"
                          >
                            <Zap className="w-3 h-3" />
                            加速
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })()}

                {/* Speed & Capital */}
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs text-slate-400 mb-1.5 block">回放倍速</label>
                    <Select value={String(speed)} onValueChange={v => setSpeed(Number(v))}>
                      <SelectTrigger className="w-full bg-slate-800 border-slate-700 text-slate-100 h-9 text-sm">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent className="bg-slate-800 border-slate-700">
                        {SPEEDS.map(s => (
                          <SelectItem key={s.value} value={String(s.value)} className="text-slate-100 focus:bg-slate-700 cursor-pointer">{s.label}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div>
                    <label className="text-xs text-slate-400 mb-1.5 block">初始资金</label>
                    <input
                      type="number"value={initialCapital}onChange={e => setInitialCapital(Number(e.target.value))}
                      className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-slate-100 focus:outline-none focus:border-blue-500"
                    />
                  </div>
                </div>

                {/* Slippage Model Info */}
                <div className="p-3 bg-slate-800/50 border border-slate-700/50 rounded-lg">
                  <div className="flex items-start gap-2">
                    <Info className="w-4 h-4 text-slate-400 shrink-0 mt-0.5" />
                    <div className="space-y-1">
                      <p className="text-xs text-slate-300 font-medium">交易成本模型</p>
                      <div className="flex items-center gap-3 text-[11px] text-slate-400">
                        <span>滑点率: <span className="text-slate-200">0.05%</span></span>
                        <span className="text-slate-600">|</span>
                        <span>手续费: <span className="text-slate-200">0.1%</span></span>
                      </div>
                      <p className="text-[10px] text-slate-500">市价单自动应用滑点，买入价上浮、卖出价下调</p>
                    </div>
                  </div>
                </div>

                {/* Start Button */}
                <Button onClick={handleCreateAndStart} disabled={!!running || (session?.status === "running")}
                  className="w-full bg-indigo-600 hover:bg-indigo-500 text-white font-bold py-3 rounded-xl shadow-lg shadow-indigo-500/20"
                >
                  {running ? <><RefreshCw className="w-4 h-4 animate-spin mr-2" /> 启动中...</> : <><Play className="w-4 h-4 mr-2" /> 开始回放</>}
                </Button>

                {error && (
                  <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-xl text-red-400 text-xs flex items-start gap-2 animate-in fade-in slide-in-from-top-1">
                    <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                    {error}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Strategy Params Sliders */}
            {/* Dynamic Selection Strategy Panel */}
            {selectedType === "dynamic_selection" && (
              <AtomicStrategyPanel
                strategies={atomicStrategies}
                onChange={setAtomicStrategies}
                templates={templates}
                evaluationPeriod={evaluationPeriod}
                onEvaluationPeriodChange={(value) => {
                  setIsEvalPeriodManual(true);
                  setEvaluationPeriod(value);
                }}
                weightMethod={weightMethod}
                onWeightMethodChange={setWeightMethod}
                compositionThreshold={compositionThreshold}
                onCompositionThresholdChange={setCompositionThreshold}
                eliminationRule={eliminationRule}
                onEliminationRuleChange={setEliminationRule}
                revivalRule={revivalRule}
                onRevivalRuleChange={setRevivalRule}
                perStrategyCapital={perStrategyCapital}
                onPerStrategyCapitalChange={setPerStrategyCapital}
                interval={interval}
                dateRange={dateRange}
                isEvalPeriodManual={isEvalPeriodManual}
              />
            )}
            {/* Regular Strategy Params */}
            {selectedType !== "dynamic_selection" && currentTemplate && currentTemplate.params.length > 0 && (
              <Card className="bg-slate-900 border-slate-700/50">
                <CardHeader className="pb-3">
                  <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
                    <div className="w-6 h-6 bg-purple-500/10 rounded flex items-center justify-center border border-purple-500/20">
                      <Settings2 className="w-3.5 h-3.5 text-purple-400" />
                    </div>
                    策略参数
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  {currentTemplate.params.map(p => (
                    <div key={p.key}>
                      <div className="flex items-center justify-between mb-1.5">
                        <label className="text-xs text-slate-300">{p.label}</label>
                        <span className="text-xs font-mono text-purple-400 bg-purple-500/10 px-2 py-0.5 rounded">
                          {paramValues[p.key] ?? p.default}
                        </span>
                      </div>
                      <input
                        type="range" min={p.min} max={p.max}step={p.step ?? (p.type === "int" ? 1 : 0.5)}value={paramValues[p.key] ?? p.default}onChange={e => setParamValues(prev => ({
                          ...prev,
                          [p.key]: p.type === "int" ? parseInt(e.target.value) : parseFloat(e.target.value),
                        }))}
                        className="w-full h-1.5 bg-slate-700 rounded-full appearance-none cursor-pointer accent-purple-500"
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
          </div>

          {/* ── Right: Replay Status & Monitoring ── */}
          <div className="lg:col-span-2 space-y-6">
            {!status ? (
              <div className="flex flex-col items-center justify-center min-h-[500px] text-slate-500 space-y-4 border-2 border-dashed border-slate-800 rounded-2xl">
                <div className="w-20 h-20 bg-slate-900/50 rounded-2xl flex items-center justify-center border border-slate-800 shadow-inner">
                  <History className="w-10 h-10 opacity-20" />
                </div>
                <div className="text-center">
                  <p className="text-base font-medium text-slate-400">准备就绪</p>
                  <p className="text-sm text-slate-600 mt-1">配置完成后点击「开始回放」即可实时观察策略表现</p>
                </div>
              </div>
            ) : (
              <div className="space-y-6 animate-in fade-in duration-500">
                {/* Replay Header */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <Badge className={`px-2 py-1 ${status.status === "running" ? "bg-green-500/10 text-green-400 border-green-500/20" :status.status === "paused" ? "bg-yellow-500/10 text-yellow-400 border-yellow-500/20" :
                      "bg-slate-700 text-slate-300"
                    }`}>
                      {status.status.toUpperCase()}
                    </Badge>
                    {/* Error Count Badge */}
                    {status.error_count && status.error_count > 0 && (
                      <button onClick={() => setShowWarningPanel(!showWarningPanel)}
                        className={`px-2 py-1 rounded-md text-xs font-medium flex items-center gap-1 transition-all ${status.error_count >= 5
                            ? "bg-red-500/10 text-red-400 border border-red-500/20 hover:bg-red-500/20"
                            : "bg-orange-500/10 text-orange-400 border border-orange-500/20 hover:bg-orange-500/20"
                        }`}
                      >
                        <AlertTriangle className="w-3.5 h-3.5" />
                        {status.error_count < 5 ? `${status.error_count} 个警告` : `${status.error_count} 个错误`}
                        {showWarningPanel ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                      </button>
                    )}
                    <div className="flex flex-col">
                      <span className="text-sm font-bold text-slate-100">{session?.symbol}</span>
                      <span className="text-[10px] text-slate-500">{selectedType.toUpperCase()} · {speed === -1 ? "极速" : `${speed}x`}</span>
                    </div>
                  </div>
                  
                  {/* Controls */}
                  <div className="flex items-center gap-2">
                    {/* Save button */}
                    {session && (
                      <button onClick={() => handleToggleSave(session.replay_session_id)}
                        className={`p-2 rounded-lg transition-all ${session.is_saved
                            ? 'bg-amber-500/20 text-amber-400 hover:bg-amber-500/30'
                            : 'bg-slate-800 text-slate-400 hover:bg-slate-700 hover:text-slate-200 border border-slate-700'
                        }`}
                        title={session.is_saved ? "取消保存" : "保存记录"}
                      >
                        {session.is_saved ? <BookmarkCheck className="w-4 h-4" /> : <Bookmark className="w-4 h-4" />}
                      </button>
                    )}
                    {status.status === "running" ? (
                      <Button variant="outline" size="sm" onClick={handlePause} className="h-8 border-slate-700 hover:bg-slate-800">
                        <Pause className="w-3.5 h-3.5 mr-1.5" /> 暂停
                      </Button>
                    ) : (status.status === "paused" || status.status === "pending") ? (
                      <Button variant="outline" size="sm" onClick={handleResume} className="h-8 bg-green-500/10 border-green-500/30 text-green-400 hover:bg-green-500/20">
                        <Play className="w-3.5 h-3.5 mr-1.5" /> {status.status === "pending" ? "开始" : "继续"}
                      </Button>
                    ) : null}
                    
                    {(status.status === "paused" || status.status === "running") && (
                      <Button 
                        variant="outline" size="sm" onClick={() => {
                          const current = new Date(status.current_simulated_time);
                          setJumpDate(current);
                          setJumpTime(`${String(current.getHours()).padStart(2, '0')}:${String(current.getMinutes()).padStart(2, '0')}`);
                          setShowJumpModal(true);
                        }} 
                        className="h-8 border-indigo-500/30 text-indigo-400 hover:bg-indigo-500/10"
                      >
                        <SkipForward className="w-3.5 h-3.5 mr-1.5" /> 跳转
                      </Button>
                    )}
                    
                    {/* Delete button - only for completed/failed/paused sessions */}
                    {(status.status === "completed" || status.status === "failed" || status.status === "paused") && session && (
                      <button onClick={() => handleDeleteSession(session.replay_session_id)}
                        className="p-2 rounded-lg bg-slate-800 text-slate-400 hover:bg-red-500/20 hover:text-red-400 transition-all border border-slate-700"
                        title="删除记录"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    )}
                  </div>
                </div>

                {/* Warning Details Panel - Collapsible */}
                {showWarningPanel && status.error_count && status.error_count > 0 && status.warnings && status.warnings.length > 0 && (
                  <Card className="bg-slate-900 border-orange-500/30 shadow-lg animate-in slide-in-from-top-2 duration-200">
                    <CardHeader className="pb-2 pt-3 px-4">
                      <CardTitle className="text-slate-100 text-sm flex items-center justify-between">
                        <span className="flex items-center gap-2">
                          <AlertTriangle className="w-4 h-4 text-orange-400" />
                          警告详情
                          <Badge variant="outline" className="text-xs border-orange-500/30 text-orange-400">
                            {status.warnings.length} 条
                          </Badge>
                        </span>
                        <button onClick={() => setShowWarningPanel(false)}
                          className="p-1 hover:bg-slate-800 rounded transition-colors"
                        >
                          <X className="w-4 h-4 text-slate-500" />
                        </button>
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="pt-0 pb-3 px-4">
                      <div className="max-h-40 overflow-y-auto space-y-1 pr-2 custom-scrollbar">
                        {status.warnings.map((warning, index) => (
                          <div key={index}
                            className="text-xs font-mono text-slate-400 bg-slate-800/50 px-2 py-1.5 rounded border border-slate-700/50"
                          >
                            <span className="text-orange-400/60 mr-1">[{index + 1}]</span>
                            {warning}
                          </div>
                        ))}
                      </div>
                    </CardContent>
                  </Card>
                )}

                {/* Progress Card */}
                <Card className="bg-slate-900 border-slate-700/50 shadow-lg overflow-hidden relative group">
                  {/* Top mini progress bar with click/drag support */}
                  <div 
                    className={`absolute top-0 left-0 w-full h-1.5 bg-slate-800 cursor-pointer ${status?.status === "paused" ? "cursor-ew-resize hover:bg-slate-700" : "cursor-default"}`}
                    onMouseMove={isDragging ? handleDragMove : calculateProgressHover}
                    onMouseLeave={() => { if (!isDragging) setHoverProgress(null); }}
                    onMouseDown={handleDragStart}
                    onMouseUp={handleDragEnd}
                    onClick={status?.status === "paused" && !isDragging ? handleProgressClick : undefined}
                  >
                    <div 
                      className={`h-full bg-indigo-500 shadow-[0_0_10px_rgba(99,102,241,0.5)] transition-all ${isDragging ? "duration-100" : "duration-500"}`} style={{ width: `${status?.progress * 100}%` }}
                    />
                    {/* Drag indicator */}
                    {isDragging && hoverProgress && (
                      <div 
                        className="absolute top-1/2 -translate-y-1/2 w-3 h-3 bg-indigo-400 rounded-full shadow-lg shadow-indigo-500/50 border-2 border-white z-20"style={{ left: `${hoverProgress.x}px`, transform: 'translateX(-50%) translateY(-50%)' }}
                      />
                    )}
                    {/* Hover tooltip */}
                    {hoverProgress && !isDragging && (
                      <div 
                        className="absolute top-4 bg-slate-800 text-slate-100 text-[10px] px-2 py-1 rounded border border-slate-600 whitespace-nowrap z-10 pointer-events-none shadow-lg"style={{ left: `${hoverProgress.x}px`, transform: 'translateX(-50%)' }}
                      >
                        {hoverProgress.time}
                        {status?.status === "paused" && (
                          <span className="ml-1 text-indigo-400">点击跳转</span>
                        )}
                      </div>
                    )}
                  </div>
                  {/* Progress hint */}
                  {showProgressHint && status?.status === "paused" && (
                    <div className="absolute top-3 right-3 bg-indigo-500/20 text-indigo-400 text-[10px] px-2 py-1 rounded animate-pulse z-20">
                      拖拽或点击进度条跳转
                    </div>
                  )}
                  <CardContent className="p-6">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                      <div className="space-y-4">
                        <div className="flex items-center gap-3">
                          <div className="w-10 h-10 bg-indigo-500/10 rounded-xl flex items-center justify-center border border-indigo-500/20">
                            <Clock className="w-5 h-5 text-indigo-400" />
                          </div>
                          <div>
                            <p className="text-[10px] text-slate-500 uppercase font-bold">当前回放时间</p>
                            <div className="flex items-baseline gap-1">
                              <p className="text-xl font-mono font-bold text-slate-100 tabular-nums">
                                {status.current_simulated_time 
                                  ? format(new Date(status.current_simulated_time), "yyyy-MM-dd HH:mm:ss") 
                                  : "----- --:--:--"}
                              </p>
                              {status.current_simulated_time && (
                                <span className="text-[10px] text-indigo-400 font-mono animate-pulse">
                                  .{String(new Date(status.current_simulated_time).getMilliseconds()).padStart(3, '0')}
                                </span>
                              )}
                            </div>
                          </div>
                        </div>
                        <div className="space-y-1.5">
                          <div className="flex justify-between text-xs">
                            <span className="text-slate-500">回放进度</span>
                            <div className="flex items-center gap-2">
                              {/* K线处理进度 */}
                              {status.bars_processed !== undefined && status.bars_total !== undefined && status.bars_total > 0 && (
                                <span className="text-slate-500 text-[10px]">
                                  K线: {status.bars_processed}/{status.bars_total}
                                </span>
                              )}
                              <span className="text-indigo-400 font-bold">{(status?.progress * 100).toFixed(1)}%</span>
                            </div>
                          </div>
                          <div 
                            className={`h-2 w-full bg-slate-800 rounded-full overflow-hidden cursor-crosshair relative ${status?.status === "paused" ? "cursor-ew-resize hover:bg-slate-700" : ""}`}onMouseMove={isDragging ? handleDragMove : calculateProgressHover}onMouseLeave={() => { if (!isDragging) setHoverProgress(null); }}onMouseDown={handleDragStart}onMouseUp={handleDragEnd} onClick={status?.status === "paused" && !isDragging ? handleProgressClick : undefined}
                          >
                            <div 
                              className={`h-full bg-indigo-500 transition-all ${isDragging ? "duration-100" : "duration-500"}`} style={{ width: `${(status?.progress || 0) * 100}%` }}
                            />
                            {/* Hover indicator line */}
                            {hoverProgress && !isDragging && (
                              <div 
                                className="absolute top-0 w-0.5 h-full bg-white/40"style={{ left: `${hoverProgress.x}px` }}
                              />
                            )}
                            {/* Drag indicator */}
                            {isDragging && hoverProgress && (
                              <div 
                                className="absolute top-1/2 -translate-y-1/2 w-3 h-3 bg-indigo-400 rounded-full shadow-lg border-2 border-white z-10"style={{ left: `${hoverProgress.x}px`, transform: 'translateX(-50%) translateY(-50%)' }}
                              />
                            )}
                            {/* Hover time tooltip */}
                            {hoverProgress && (
                              <div 
                                className="absolute -top-8 left-1/2 -translate-x-1/2 bg-slate-700 text-slate-100 text-[10px] px-2 py-1 rounded border border-slate-600 whitespace-nowrap z-20 pointer-events-none"
                              >
                                {hoverProgress.time}
                                {status?.status === "paused" && (
                                  <span className="ml-1 text-indigo-400">→ 点击跳转</span>
                                )}
                              </div>
                            )}
                          </div>
                        </div>
                      </div>

                      <div className="flex items-center justify-between p-4 bg-slate-800/30 rounded-2xl border border-slate-700/30">
                        <div>
                          <p className="text-[10px] text-slate-500 uppercase font-bold">当前浮盈 (PNL)</p>
                          <p className={`text-2xl font-bold font-mono ${status.pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                            {status.pnl >= 0 ? "+" : ""}${status.pnl.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                          </p>
                        </div>
                        <div className={`w-12 h-12 rounded-xl flex items-center justify-center border ${status.pnl >= 0 ? "bg-green-500/10 border-green-500/20 text-green-400" : "bg-red-500/10 border-red-500/20 text-red-400"}`}>
                          {status.pnl >= 0 ? <TrendingUp className="w-6 h-6" /> : <TrendingDown className="w-6 h-6" />}
                        </div>
                      </div>
                    </div>
                    {/* 无交易信号提示 - 当回放完成但无交易时显示 */}
                    {status.status === "completed" && tradeList.length === 0 && (
                      <div className="mt-3 p-3 rounded-lg bg-yellow-500/10 border border-yellow-500/30">
                        <p className="text-yellow-400 text-sm">
                          ⚠ 该策略在选定时间段内未产生交易信号。建议：调整策略参数、更换策略类型、或扩大回放时间范围。
                        </p>
                      </div>
                    )}
                  </CardContent>
                </Card>

                {/* Info Card */}
                <div className="grid grid-cols-3 gap-4">
                  <div className="p-4 bg-slate-900 border border-slate-700/50 rounded-xl">
                    <p className="text-[10px] text-slate-500 uppercase font-bold mb-1">开始时间</p>
                    <p className="text-xs text-slate-300">
                      {session?.start_time ? new Date(session.start_time).toLocaleDateString() : "---"}
                    </p>
                  </div>
                  <div className="p-4 bg-slate-900 border border-slate-700/50 rounded-xl">
                    <p className="text-[10px] text-slate-500 uppercase font-bold mb-1">结束时间</p>
                    <p className="text-xs text-slate-300">
                      {session?.end_time ? new Date(session.end_time).toLocaleDateString() : "---"}
                    </p>
                  </div>
                  <div className="p-4 bg-slate-900 border border-slate-700/50 rounded-xl">
                    <p className="text-[10px] text-slate-500 uppercase font-bold mb-1">初始资金</p>
                    <p className="text-xs text-slate-300">
                      {session?.initial_capital ? `$${session.initial_capital.toLocaleString()}` : "---"}
                    </p>
                  </div>
                </div>

                {/* Time Comparison Card - Show estimated vs actual */}
                {status?.elapsed_seconds !== undefined && (
                  <div className="p-4 bg-slate-900 border border-slate-700/50 rounded-xl">
                    <p className="text-[10px] text-slate-500 uppercase font-bold mb-2 flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      回放时间统计
                    </p>
                    <div className="grid grid-cols-2 gap-4">
                      <div className="bg-slate-800/50 rounded-lg p-2">
                        <p className="text-[10px] text-slate-500">理论时间</p>
                        <p className="text-sm font-medium text-slate-300">
                          {(() => {
                            if (!validDates || validDates.length === 0) return "---";
                            const startDate = new Date(dateRange.start);
                            const endDate = new Date(dateRange.end);
                            const days = Math.max(1, Math.ceil((endDate.getTime() - startDate.getTime()) / 86400000));
                            const dataPoints = estimateDataPoints(days, interval);
                            const theoretical = calculateTheoreticalTime(dataPoints, interval, session?.speed || speed);
                            return theoretical.display;
                          })()}
                        </p>
                      </div>
                      <div className="bg-slate-800/50 rounded-lg p-2 border border-amber-500/20">
                        <p className="text-[10px] text-slate-500 flex items-center gap-1">
                          <Zap className="w-3 h-3 text-amber-400" />
                          实际消耗
                        </p>
                        <p className="text-sm font-bold text-amber-400">
                          {formatElapsedTime(status.elapsed_seconds || 0)}
                        </p>
                      </div>
                    </div>
                    {/* Performance indicator */}
                    {status?.elapsed_seconds && status.elapsed_seconds > 0 && (() => {
                      const actualSec = status.elapsed_seconds;
                      const startDate = new Date(dateRange.start);
                      const endDate = new Date(dateRange.end);
                      const days = Math.max(1, Math.ceil((endDate.getTime() - startDate.getTime()) / 86400000));
                      const totalBars = estimateDataPoints(days, interval);
                      const progressRatio = status.progress ?? 0;                 // 0-1
                      const progressPct = Math.round(progressRatio * 100);        // 0-100
                      const processedBars = Math.floor(totalBars * progressRatio);
                      const barsPerSec = processedBars > 0 ? Math.round(processedBars / actualSec) : 0;
                      
                      return (
                        <div className="mt-3 pt-3 border-t border-slate-700/50">
                          <div className="flex items-center justify-between text-[10px] text-slate-500 mb-1.5">
                            <span>处理进度</span>
                            <span className="text-slate-400">{progressPct}%</span>
                          </div>
                          <div className="w-full bg-slate-800 rounded-full h-1.5 mb-2">
                            <div 
                              className="bg-indigo-500 h-1.5 rounded-full transition-all duration-300"style={{ width: `${progressPct}%` }}
                            />
                          </div>
                          <div className="flex items-center justify-between text-[10px]">
                            <span className="text-slate-500">处理速度</span>
                            <span className="text-indigo-400">{barsPerSec > 0 ? `${barsPerSec.toLocaleString()} 根/秒` : "---"}</span>
                          </div>
                        </div>
                      );
                    })()}
                  </div>
                )}
                
                {/* K线图表区域 - 回放进行中或完成时显示 */}
                {(status?.status === "running" || status?.status === "paused" || status?.status === "completed") && klineData.length > 0 && (
                  <Card className="bg-slate-900 border-slate-700/50">
                    <CardHeader className="pb-2">
                      <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
                        <BarChart3 className="w-4 h-4 text-purple-400" />
                        K线图 · {session?.symbol} · {session?.interval || session?.params?.interval || "15m"}
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="p-2">
                      <KlineChart klines={klineData} indicators={indicatorData} markers={(tradeMarkers || []).map(m => ({ ...m, pnl: m.pnl ?? null, quantity: m.quantity ?? 0 }))} strategyType={session?.strategy_type || selectedType || "ma"} height={400} />
                    </CardContent>
                  </Card>
                )}

                {/* Equity Curve Chart */}
                <Card className="bg-slate-900 border-slate-700/50">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
                      <TrendingUp className="w-4 h-4 text-indigo-400" />
                      资产曲线
                      {tradeMarkers.length > 0 && (
                        <span className="text-xs font-normal text-slate-400 ml-1">
                          ({tradeMarkers.length} 笔交易)
                        </span>
                      )}
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="p-0 pb-2">
                    <div className="px-4">
                      <EquityCurveChart data={equityCurveData}baselineData={baselineCurveData}markers={tradeMarkers}initialCapital={session?.initial_capital || 100000}height={250}
                      />
                    </div>
                  </CardContent>
                </Card>
                
                {/* 交易列表 + 持仓面板 并排 */}
                {(status?.status === "running" || status?.status === "paused" || status?.status === "completed") && (
                  <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                    <div className="lg:col-span-2">
                      <TradeList trades={tradeList} height={300} />
                    </div>
                    <div className="lg:col-span-1">
                      <PositionPanel position={positionInfo} />
                    </div>
                  </div>
                )}

                {/* Dynamic Selection 策略专用：淘汰历史 + 权重变化图表 */}
                {safeSession?.strategy_type === "dynamic_selection" && safeSession?.replay_session_id && (
                  <div className="space-y-4 mt-4">
                    <EliminationHistory
                      sessionId={safeSession.replay_session_id}
                      isRunning={running}
                      data={dynamicSelectionHistory}
                    />
                    <WeightEvolutionChart
                      sessionId={safeSession.replay_session_id}
                      isRunning={running}
                      data={dynamicSelectionHistory}
                    />
                  </div>
                )}

                {/* Attribution Link */}
                <div className="pt-4 flex justify-between items-center">
                  <Link href={`/analytics?mode=historical_replay&session_id=${session?.replay_session_id}`}>
                     <Button variant="outline" className="text-xs border-indigo-500/30 text-indigo-400 hover:bg-indigo-500/10">
                       查看回放归因分析 <ChevronRight className="w-3.5 h-3.5 ml-1" />
                     </Button>
                  </Link>
                  <Button
                    variant="outline"onClick={() => handleQuickBacktest()} disabled={quickBacktestLoading || !session}
                    className="text-xs border-cyan-500/30 text-cyan-400 hover:bg-cyan-500/10 flex items-center gap-1.5"
                  >
                    {quickBacktestLoading ? (
                      <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <BarChart2 className="w-3.5 h-3.5" />
                    )}
                    {quickBacktestLoading ? "运行回测中..." : "快速对比回测"}
                    {!quickBacktestLoading && <ChevronRight className="w-3.5 h-3.5 ml-1" />}
                  </Button>
                </div>
              </div>
            )}
          </div>
        </div>
      </main>

      {/* Jump Modal */}
      {showJumpModal && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-lg shadow-2xl animate-in zoom-in-95 duration-200">
            <div className="p-6 border-b border-slate-800">
              <div className="flex items-center justify-between">
                <h3 className="text-lg font-bold text-slate-100 flex items-center gap-2">
                  <SkipForward className="w-5 h-5 text-indigo-400" />
                  精准跳转回放点
                </h3>
                <button onClick={() => setShowJumpModal(false)} className="text-slate-500 hover:text-slate-200 transition-colors">
                  <X className="w-5 h-5" />
                </button>
              </div>
              <p className="text-xs text-slate-500 mt-2">跳转后，回放将从该时间点继续。注意：跳转可能会重置部分未成交的模拟订单。</p>
            </div>
            <div className="p-6 space-y-6">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <label className="text-xs text-slate-400 block">选择日期</label>
                  <Popover>
                    <PopoverTrigger asChild>
                      <Button
                        variant={"outline"}
                        className={cn(
                          "w-full justify-start text-left font-normal bg-slate-800 border-slate-700 text-slate-100 h-10 px-3",
                          !jumpDate && "text-slate-500"
                        )}
                      >
                        <CalendarIcon className="mr-2 h-4 w-4 text-slate-400" />
                        {jumpDate ? format(jumpDate, "PPP") : <span>选择日期</span>}
                      </Button>
                    </PopoverTrigger>
                    <PopoverContent className="w-auto p-0 bg-slate-900 border-slate-700" align="start">
                      <Calendar mode="single"selected={jumpDate} onSelect={setJumpDate}initialFocus fromDate={validDates.length > 0 ? new Date(validDates[0]) : undefined}toDate={validDates.length > 0 ? new Date(validDates[validDates.length - 1]) : undefined} disabled={(day) => !isDateValid(day)}modifiers={{hasData: (day) => isDateValid(day),
                        }}modifiersClassNames={{hasData: "after:content-[''] after:absolute after:bottom-1 after:left-1/2 after:-translate-x-1/2 after:w-1 after:h-1 after:bg-blue-500 after:rounded-full",
                        }}
                      />
                    </PopoverContent>
                  </Popover>
                </div>
                <div className="space-y-2">
                  <label className="text-xs text-slate-400 block">选择时间</label>
                  <div className="relative">
                    <Clock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                    <input
                      type="time"value={jumpTime}onChange={(e) => setJumpTime(e.target.value)}
                      className="w-full bg-slate-800 border border-slate-700 rounded-lg pl-10 pr-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-indigo-500 transition-all"
                    />
                  </div>
                </div>
              </div>

              <div className="p-3 bg-indigo-500/10 border border-indigo-500/20 rounded-xl">
                <p className="text-[10px] text-indigo-400 font-bold uppercase mb-1">目标时间 (Local)</p>
                <p className="text-sm font-mono text-slate-100">
                  {jumpDate ? format(jumpDate, "yyyy-MM-dd") : "-----"} {jumpTime}:00
                </p>
              </div>

              <div className="flex gap-3">
                <Button variant="ghost" onClick={() => setShowJumpModal(false)} className="flex-1 text-slate-400">取消</Button>
                <Button onClick={handleJump} className="flex-1 bg-indigo-600 hover:bg-indigo-500 text-white font-bold shadow-lg shadow-indigo-500/20">
                  确认跳转
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Toast Notification */}
      {toast && (
        <div className={cn(
          "fixed bottom-6 right-6 z-[100] px-4 py-3 rounded-xl border shadow-2xl animate-in slide-in-from-bottom-4 duration-300 flex items-center gap-3",toast.type === "error" ? "bg-red-950 border-red-500/50 text-red-200" :toast.type === "success" ? "bg-green-950 border-green-500/50 text-green-200" :
          "bg-slate-900 border-slate-700 text-slate-200"
        )}>
          {toast.type === "error" ? <AlertTriangle className="w-5 h-5 text-red-400" /> :
           toast.type === "success" ? <CheckCircle2 className="w-5 h-5 text-green-400" /> :
           <Info className="w-5 h-5 text-indigo-400" />}
          <span className="text-sm font-medium">{toast.message}</span>
          <button onClick={() => setToast(null)} className="ml-2 text-slate-500 hover:text-slate-200">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}
    </div>
  );
}
