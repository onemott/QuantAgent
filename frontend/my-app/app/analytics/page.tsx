"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  ArrowLeft, RefreshCw, TrendingUp, TrendingDown,
  BarChart3, PieChart as PieChartIcon, Activity, DollarSign, Target,
  Zap, AlertTriangle, Clock, Wallet, ChevronDown, ChevronRight,
} from "lucide-react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  AreaChart, Area, PieChart, Pie, Cell, BarChart, Bar, Legend,
} from "recharts";
import { DataSourceBadge } from "@/components/analytics/DataSourceBadge";
import { ComparisonWarningBanner } from "@/components/analytics/ComparisonWarningBanner";

const API_BASE = ""; // 客户端请求强制使用相对路径，通过 Next.js rewrites 转发到后端

interface PerformanceMetrics {
  initial_capital: number | null;
  final_equity: number | null;
  total_return: number | null;
  total_pnl: number | null;
  total_trades: number | null;
  winning_trades: number | null;
  losing_trades: number | null;
  win_rate: number | null;
  profit_factor: number | null;
  total_profit: number | null;
  total_loss: number | null;
  avg_profit: number | null;
  avg_loss: number | null;
  max_drawdown: number | null;
  max_drawdown_pct: number | null;
  volatility: number | null;
  annualized_return: number | null;
  sharpe_ratio: number | null;
  sortino_ratio: number | null;
  calmar_ratio: number | null;
  avg_holding_hours: number | null;
  max_consecutive_wins: number | null;
  max_consecutive_losses: number | null;
  // 新增字段
  max_drawdown_duration: number | null; // 最大回撤持续天数
  var_95: number | null; // 95% VaR
}

interface EquityPoint {
  timestamp: string;
  total_equity: number;
  cash_balance: number;
  position_value: number;
  daily_pnl: number;
  daily_return: number;
  drawdown: number;
}

interface PortfolioData {
  total_equity: number;
  cash: number;
  position_value: number;
  cash_pct: number;
  total_unrealized_pnl: number;
  asset_allocation: Array<{
    symbol: string;
    value: number;
    allocation_pct: number;
    side: string;
  }>;
  exposure: {
    long: number;
    short: number;
    net_exposure: number;
    gross_exposure: number;
    leverage: number;
  };
  position_count: number;
  timestamp: string;
}

export default function AnalyticsPage() {
  const searchParams = useSearchParams();
  const [globalMetrics, setGlobalMetrics] = useState<PerformanceMetrics | null>(null);
  const [sessionMetrics, setSessionMetrics] = useState<PerformanceMetrics | null>(null);
  const [equityCurve, setEquityCurve] = useState<EquityPoint[]>([]);
  const [portfolio, setPortfolio] = useState<PortfolioData | null>(null);
  const [attribution, setAttribution] = useState<any[]>([]);
  const [strategyAttribution, setStrategyAttribution] = useState<any>(null);
  const [replaySessions, setReplaySessions] = useState<any[]>([]);
  const [selectedStrategy, setSelectedStrategy] = useState<string>("auto_trend_ma");
  const [compareMode, setCompareMode] = useState<string>("paper");
  const [replaySessionId, setReplaySessionId] = useState<string>("");
  const [comparison, setComparison] = useState<any[]>([]);
  const [period, setPeriod] = useState("all_time");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  // 回放 vs 回测对比数据
  const [rbComparison, setRbComparison] = useState<any>(null);
  const [rbComparisonLoading, setRbComparisonLoading] = useState(false);
  const [selectedRbSession, setSelectedRbSession] = useState<string>("");
  const [rbEquityData, setRbEquityData] = useState<any>(null);
  const [comparisonEquity, setComparisonEquity] = useState<any>(null);

  // 增强归因分析状态
  const [enhancedAttribution, setEnhancedAttribution] = useState<any>(null);
  const [enhancedAttrLoading, setEnhancedAttrLoading] = useState(false);
  const [attrMode, setAttrMode] = useState<string>("backtest");
  const [attrSessionId, setAttrSessionId] = useState<string>("");
  const [completedReplaySessions, setCompletedReplaySessions] = useState<any[]>([]);
  const [tradeLevelExpanded, setTradeLevelExpanded] = useState(false);

  const [showMockData, setShowMockData] = useState(false);
  const [hasMockDataWarning, setHasMockDataWarning] = useState(false);

  // 会话驱动模式状态 - Session-Driven Mode
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [selectedSessionInfo, setSelectedSessionInfo] = useState<any>(null);
  const [sessionTrades, setSessionTrades] = useState<any[]>([]);
  const [sessionEquityData, setSessionEquityData] = useState<any>(null);
  const [sessionComparisonData, setSessionComparisonData] = useState<any>(null);
  const [sessionLoading, setSessionLoading] = useState(false);
  const [sessionError, setSessionError] = useState<string | null>(null);

  // 用于防止异步竞态条件的请求 ID
  const sessionRequestIdRef = useRef(0);

  const fetchReplaySessions = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/replay/sessions`);
      if (res.ok) {
        const data = await res.json();
        setReplaySessions(data.sessions || []);  // 解构分页响应中的 sessions 字段
      }
    } catch (e) {
      console.error("Failed to fetch replay sessions:", e);
    }
  };

  // 获取已完成的回放会话列表（用于归因分析和对比）
  const fetchCompletedReplaySessions = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/replay/sessions?status=completed&page_size=50`);
      if (res.ok) {
        const data = await res.json();
        setCompletedReplaySessions(data.sessions || []);  // 解构分页响应中的 sessions 字段
      }
    } catch (e) {
      console.error("Failed to fetch completed replay sessions:", e);
    }
  }, []);

  // 获取特定会话的指标数据 - Session-Driven Data Fetching
  const fetchSessionData = useCallback(async (sessionId: string) => {
    const requestId = ++sessionRequestIdRef.current;  // 递增请求 ID
    setSessionLoading(true);
    setSessionError(null);  // 清除旧错误
    setSessionMetrics(null);  // 先清空会话指标，防止短暂显示旧数据
    try {
      // 找到会话信息
      const sessionInfo = completedReplaySessions.find(s => s.replay_session_id === sessionId);
      setSelectedSessionInfo(sessionInfo || null);

      // 并行请求所有会话相关数据
      const [metricsRes, equityRes, comparisonRes, tradesRes] = await Promise.all([
        fetch(`${API_BASE}/api/v1/analytics/performance?replay_session_id=${sessionId}&period=all_time&include_mock=${showMockData}`),
        fetch(`${API_BASE}/api/v1/analytics/replay-backtest-equity?replay_session_id=${sessionId}&include_mock=${showMockData}`),
        fetch(`${API_BASE}/api/v1/analytics/replay-backtest-comparison?replay_session_id=${sessionId}&include_mock=${showMockData}`),
        fetch(`${API_BASE}/api/v1/replay/${sessionId}/trades`),
      ]);

      // 检查是否仍是最新请求，如果不是则丢弃结果
      if (requestId !== sessionRequestIdRef.current) return;

      // 处理性能指标
      if (metricsRes.ok) {
        const metricsData = await metricsRes.json();
        setSessionMetrics(metricsData);
      }

      // 处理权益曲线数据
      if (equityRes.ok) {
        const equityData = await equityRes.json();
        setSessionEquityData(equityData);
      }

      // 处理对比数据
      if (comparisonRes.ok) {
        const comparisonData = await comparisonRes.json();
        setSessionComparisonData(comparisonData);
        setRbComparison(comparisonData);
      }

      // 处理交易流水
      if (tradesRes.ok) {
        const tradesData = await tradesRes.json();
        setSessionTrades(tradesData.trades || []);
      }
    } catch (e) {
      if (requestId !== sessionRequestIdRef.current) return;  // 丢弃过期的错误
      const msg = e instanceof Error ? e.message : "网络错误";
      setSessionError(`加载会话数据失败: ${msg}`);
      console.error("Failed to fetch session data:", e);
    } finally {
      if (requestId === sessionRequestIdRef.current) {
        setSessionLoading(false);
      }
    }
  }, [completedReplaySessions, showMockData]);

  // 监听 selectedSessionId 变化触发数据重新加载
  useEffect(() => {
    if (selectedSessionId) {
      setSessionError(null);  // 清除旧错误
      fetchSessionData(selectedSessionId);
      setSelectedRbSession(selectedSessionId); // 同步到回放对比选择器
    } else {
      // 清空会话相关数据，恢复全局模式
      setSessionError(null);
      setSelectedSessionInfo(null);
      setSessionTrades([]);
      setSessionEquityData(null);
      setSessionComparisonData(null);
      setSessionMetrics(null);  // 清空会话指标，自动回退到globalMetrics
      fetchData(); // 重新加载全局数据
    }
  }, [selectedSessionId]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const attributionUrl = `${API_BASE}/api/v1/analytics/attribution/strategy/${selectedStrategy}?base_mode=backtest&compare_mode=${compareMode}${replaySessionId ? `&replay_session_id=${replaySessionId}` : ""}`;
      
      const [metricsRes, equityRes, portfolioRes, attributionRes, comparisonRes, strategyAttrRes] = await Promise.all([
        fetch(`${API_BASE}/api/v1/analytics/performance?period=${period}&include_mock=${showMockData}`),
        fetch(`${API_BASE}/api/v1/analytics/equity-curve?period=${period}&include_mock=${showMockData}`),
        fetch(`${API_BASE}/api/v1/analytics/positions/analysis?include_mock=${showMockData}`),
        fetch(`${API_BASE}/api/v1/analytics/attribution?period=${period}&include_mock=${showMockData}`),
        fetch(`${API_BASE}/api/v1/analytics/strategy-comparison?include_mock=${showMockData}`),
        fetch(attributionUrl),
      ]);

      const errors: string[] = [];
      if (metricsRes.ok) setGlobalMetrics(await metricsRes.json());
      else errors.push(`性能数据 (${metricsRes.status})`);
      
      if (equityRes.ok) {
        const eqData = await equityRes.json();
        setEquityCurve(eqData.curve || []);
      } else {
        errors.push(`权益曲线 (${equityRes.status})`);
      }
      
      if (portfolioRes.ok) setPortfolio(await portfolioRes.json());
      else errors.push(`持仓分析 (${portfolioRes.status})`);

      if (attributionRes.ok) {
        const attrData = await attributionRes.json();
        setAttribution(attrData.attribution || []);
      }

      if (comparisonRes.ok) {
        const compData = await comparisonRes.json();
        setComparison(compData.comparison || []);
      }

      if (strategyAttrRes.ok) {
        const attrData = await strategyAttrRes.json();
        setStrategyAttribution(attrData);
      }

      if (errors.length > 0) {
        setError(`部分数据请求失败: ${errors.join(", ")}，请检查后端服务是否运行`);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "网络错误";
      setError(`无法连接到服务器: ${msg}，请确保后端服务已启动`);
    } finally {
      setLoading(false);
    }
  }, [period, selectedStrategy, compareMode, replaySessionId, showMockData]);

  useEffect(() => {
    fetchReplaySessions();
    fetchCompletedReplaySessions();
    fetchData();
  }, [fetchData, fetchCompletedReplaySessions]);

  // 处理 URL 参数中的回放会话 ID - 支持多种参数格式
  useEffect(() => {
    const rbSession = searchParams.get("rb_session") || searchParams.get("replay_session_id");
    const mode = searchParams.get("mode");
    const sessionId = searchParams.get("session_id");
    const backtestId = searchParams.get("backtest_id");

    // 优先使用 rb_session 或 replay_session_id 参数
    if (rbSession) {
      setSelectedSessionId(rbSession);
      setSelectedRbSession(rbSession);
      // 如果 URL 中有 backtest_id，说明是"快速对比回测"刚生成的新回测，直接用它
      if (backtestId) {
        fetchRbComparisonWithBacktestId(rbSession, Number(backtestId));
      }
    } else if (mode === "historical_replay" && sessionId) {
      // 支持 ?mode=historical_replay&session_id={id} 格式
      setSelectedSessionId(sessionId);
      setSelectedRbSession(sessionId);
    } else if (sessionId) {
      // 直接使用 session_id 参数
      setSelectedSessionId(sessionId);
      setSelectedRbSession(sessionId);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  // 专门用于"快速对比回测"：指定 replay_session 和 backtest_id，绕过自动匹配逻辑
  const fetchRbComparisonWithBacktestId = useCallback(async (sessionId: string, backtestId: number) => {
    setRbComparisonLoading(true);
    try {
      const params = new URLSearchParams();
      params.append("replay_session_id", sessionId);
      params.append("backtest_id", String(backtestId));

      const res = await fetch(`${API_BASE}/api/v1/analytics/replay-backtest-comparison?${params}&include_mock=${showMockData}`);
      if (res.ok) {
        const data = await res.json();
        setRbComparison(data);
        // 同时获取权益曲线
        const equityRes = await fetch(
          `${API_BASE}/api/v1/analytics/replay-backtest-equity?replay_session_id=${sessionId}&backtest_id=${backtestId}&include_mock=${showMockData}`
        );
        if (equityRes.ok) {
          const eqData = await equityRes.json();
          setComparisonEquity(eqData);
        }
      }
    } catch (e) {
      console.error("Failed to fetch replay-backtest comparison with backtest_id:", e);
    } finally {
      setRbComparisonLoading(false);
    }
  }, [showMockData]);

  // 获取回放 vs 回测对比数据
  const fetchRbComparison = useCallback(async (sessionId?: string) => {
    setRbComparisonLoading(true);
    try {
      const params = new URLSearchParams();
      if (sessionId) params.append("replay_session_id", sessionId);
      
      const res = await fetch(`${API_BASE}/api/v1/analytics/replay-backtest-comparison?${params}&include_mock=${showMockData}`);
      if (res.ok) {
        const data = await res.json();
        setRbComparison(data);
        if (data.replay_session && !sessionId) {
          setSelectedRbSession(data.replay_session.replay_session_id);
        }
        // Also fetch comparison equity curve
        const equityRes = await fetch(`${API_BASE}/api/v1/analytics/replay-backtest-equity?replay_session_id=${data.replay_session?.replay_session_id}&include_mock=${showMockData}`);
        if (equityRes.ok) {
          const eqData = await equityRes.json();
          setComparisonEquity(eqData);
        }
      }
    } catch (e) {
      console.error("Failed to fetch replay-backtest comparison:", e);
    } finally {
      setRbComparisonLoading(false);
    }
  }, [showMockData]);

  // 获取权益曲线对比数据
  const fetchRbEquity = useCallback(async (sessionId: string, backtestId?: number) => {
    try {
      const params = new URLSearchParams({ replay_session_id: sessionId });
      if (backtestId) params.append("backtest_id", String(backtestId));
      
      const res = await fetch(`${API_BASE}/api/v1/analytics/replay-backtest-equity?${params}&include_mock=${showMockData}`);
      if (res.ok) {
        const data = await res.json();
        setRbEquityData(data);
      }
    } catch (e) {
      console.error("Failed to fetch equity comparison:", e);
    }
  }, [showMockData]);

  // 获取增强归因分析数据
  const fetchEnhancedAttribution = useCallback(async () => {
    if (!selectedStrategy) return;
    
    setEnhancedAttrLoading(true);
    try {
      const params = new URLSearchParams({ mode: attrMode });
      if (attrMode === "historical_replay" && attrSessionId) {
        params.append("session_id", attrSessionId);
      }
      
      const res = await fetch(
        `${API_BASE}/api/v1/analytics/attribution/enhanced/${selectedStrategy}?${params}`
      );
      
      if (res.ok) {
        const data = await res.json();
        setEnhancedAttribution(data);
      } else if (res.status === 404) {
        setEnhancedAttribution({ error: "暂无数据", noData: true });
      } else {
        setEnhancedAttribution({ error: `请求失败 (${res.status})` });
      }
    } catch (e) {
      setEnhancedAttribution({ error: "网络连接失败" });
    } finally {
      setEnhancedAttrLoading(false);
    }
  }, [selectedStrategy, attrMode, attrSessionId]);

  // 当选择回放会话变化时，获取对比数据和权益曲线
  useEffect(() => {
    if (selectedRbSession) {
      fetchRbComparison(selectedRbSession);
      fetchRbEquity(selectedRbSession);
    } else {
      fetchRbComparison();
    }
  }, [selectedRbSession, fetchRbComparison, fetchRbEquity]);

  useEffect(() => {
    if (rbComparison?.comparisons?.length > 0) {
      fetchRbEquity(selectedRbSession, rbComparison.backtest_results?.[0]?.id);
    }
  }, [rbComparison]);

  // 当归因模式或会话变化时重新获取增强归因数据
  useEffect(() => {
    fetchEnhancedAttribution();
  }, [fetchEnhancedAttribution]);

  // Check if we have any non-mock data
  useEffect(() => {
    const m = selectedSessionId ? sessionMetrics : globalMetrics;
    if (!showMockData && m && Object.keys(m).length > 0) {
      setHasMockDataWarning(m.total_trades === 0);
    }
  }, [globalMetrics, sessionMetrics, selectedSessionId, showMockData]);

  // 当选择了回放会话时使用 sessionMetrics，否则使用 globalMetrics
  // 当 selectedSessionId 有值但 sessionMetrics 为 null 时，activeMetrics 为 null（显示 loading）
  const activeMetrics = selectedSessionId ? sessionMetrics : globalMetrics;

  // 格式化函数 - 处理 null 值显示 N/A
  const formatPct = (v: number | undefined | null, showNA = false) => {
    if (v == null) return showNA ? "N/A" : "0.00%";
    return `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
  };

  // 安全日期格式化函数 - 处理空值和无效日期
  const safeFormatDate = (dateString: string | undefined | null): string => {
    if (!dateString) return 'N/A';
    try {
      const date = new Date(dateString);
      if (isNaN(date.getTime())) {
        // 尝试修复常见的非标准格式
        const normalized = dateString.replace(' ', 'T').trim();
        const fixedDate = new Date(normalized.endsWith('Z') || normalized.includes('+') ? normalized : normalized + 'Z');
        if (isNaN(fixedDate.getTime())) return 'N/A';
        return fixedDate.toLocaleString('zh-CN');
      }
      return date.toLocaleString('zh-CN');
    } catch {
      return 'N/A';
    }
  };

  // 安全日期格式化函数（仅日期部分）- 用于选择器等只需要日期的场景
  const safeFormatDateShort = (dateString: string | undefined | null): string => {
    if (!dateString) return 'N/A';
    try {
      const date = new Date(dateString);
      if (isNaN(date.getTime())) {
        const normalized = dateString.replace(' ', 'T').trim();
        const fixedDate = new Date(normalized.endsWith('Z') || normalized.includes('+') ? normalized : normalized + 'Z');
        if (isNaN(fixedDate.getTime())) return 'N/A';
        return fixedDate.toLocaleDateString('zh-CN');
      }
      return date.toLocaleDateString('zh-CN');
    } catch {
      return 'N/A';
    }
  };

  const formatMoney = (v: number | undefined | null, showNA = false) => {
    if (v == null) return showNA ? "N/A" : "$0.00";
    return `$${v.toFixed(2)}`;
  };
  const formatNumber = (v: number | undefined | null, decimals = 2, showNA = false) => {
    if (v == null) return showNA ? "N/A" : "0";
    return v.toFixed(decimals);
  };
  const getValueColor = (v: number | null | undefined, positiveColor = "text-green-400", negativeColor = "text-red-400", neutralColor = "text-slate-400") => {
    if (v == null) return neutralColor;
    if (v > 0) return positiveColor;
    if (v < 0) return negativeColor;
    return neutralColor;
  };

  const formatTime = (timestamp: string) => {
    const d = new Date(timestamp);
    return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours()}:00`;
  };

  // Merge normalized equity curves for chart display
  const mergeEquityData = (eq: { normalized_replay?: Array<{ timestamp: string; return_pct: number }>; normalized_backtest?: Array<{ timestamp: string; return_pct: number }> }) => {
    const merged: Array<{ index: number; replay?: number; backtest?: number }> = [];
    const replayMap = new Map((eq.normalized_replay || []).map((r, i) => [i, r.return_pct]));
    const backtestMap = new Map((eq.normalized_backtest || []).map((b, i) => [i, b.return_pct]));
    const maxLen = Math.max(replayMap.size, backtestMap.size);
    for (let i = 0; i < maxLen; i++) {
      merged.push({ index: i, replay: replayMap.get(i), backtest: backtestMap.get(i) });
    }
    return merged;
  };

  const STRATEGY_COLORS = ["#3b82f6", "#8b5cf6", "#eab308", "#ef4444", "#10b981", "#6366f1"];

  const chartData = equityCurve.map(p => ({
    time: formatTime(p.timestamp),
    equity: p.total_equity,
    drawdown: p.drawdown,
  }));

  return (
    <div className="min-h-screen bg-slate-950">
      {/* Header */}
      <header className="border-b border-slate-800 bg-slate-900/50 backdrop-blur-sm sticky top-0 z-40">
        <div className="container mx-auto px-4 py-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Link href="/dashboard" className="text-slate-400 hover:text-slate-100 transition-colors">
                <ArrowLeft className="w-5 h-5" />
              </Link>
              <div className="w-9 h-9 bg-gradient-to-br from-purple-500 to-pink-600 rounded-xl flex items-center justify-center">
                <BarChart3 className="w-5 h-5 text-white" />
              </div>
              <div>
                <h1 className="text-lg font-bold text-slate-100">性能分析</h1>
                <p className="text-[10px] text-slate-400">Performance Analytics</p>
              </div>
            </div>
            <div className="flex items-center gap-3 flex-wrap">
              {/* 回放会话选择器 - Session Selector */}
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-400 hidden sm:inline">查看会话:</span>
                <select 
                  className="bg-slate-800 border border-slate-700 text-slate-200 text-xs rounded p-1.5 min-w-[200px] max-w-[320px]"
                  value={selectedSessionId || ""}
                  onChange={(e) => setSelectedSessionId(e.target.value || null)}
                >
                  <option value="">全局汇总</option>
                  {completedReplaySessions.map(s => {
                    const startDate = safeFormatDateShort(s.start_time);
                    const endDate = safeFormatDateShort(s.end_time);
                    return (
                      <option key={s.replay_session_id} value={s.replay_session_id}>
                        {s.strategy_type?.toUpperCase()} | {s.symbol} | {startDate} ~ {endDate}
                      </option>
                    );
                  })}
                </select>
              </div>
              <Tabs value={period} onValueChange={setPeriod}>
                <TabsList className="hidden sm:flex">
                  <TabsTrigger value="daily">今日</TabsTrigger>
                  <TabsTrigger value="weekly">本周</TabsTrigger>
                  <TabsTrigger value="monthly">本月</TabsTrigger>
                  <TabsTrigger value="all_time">全部</TabsTrigger>
                </TabsList>
              </Tabs>
              <button
                onClick={() => setShowMockData(!showMockData)}
                className={`text-xs px-3 py-1.5 rounded border transition-colors h-8 ${
                  showMockData
                    ? "bg-yellow-100 border-yellow-300 text-yellow-800"
                    : "bg-gray-50 border-gray-300 text-gray-600 hover:bg-gray-100"
                }`}
              >
                {showMockData ? "隐藏演示数据" : "显示演示数据"}
              </button>
              <Button variant="ghost" size="sm" className="h-8 text-xs text-slate-400 hover:text-slate-100" onClick={fetchData}>
                <RefreshCw className={`w-3 h-3 mr-1 ${loading ? "animate-spin" : ""}`} /> 刷新
              </Button>
              <Link href="/replay">
                <Button variant="ghost" size="sm" className="h-8 text-xs text-slate-400 hover:text-slate-100">
                  <Clock className="w-3 h-3 mr-1" /> 历史回放
                </Button>
              </Link>
              <Link href="/trades">
                <Button variant="outline" size="sm" className="h-8 text-xs border-blue-500/30 text-blue-400 hover:bg-blue-500/10">
                  交易流水
                </Button>
              </Link>
            </div>
          </div>
        </div>
      </header>

      <main className="container mx-auto px-4 py-6 space-y-6">
        {/* 选中会话的信息横幅 - Session Info Banner */}
        {selectedSessionInfo && (
          <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-4">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-blue-400 font-semibold">回放会话指标</span>
              <span className="text-xs bg-blue-500/20 px-2 py-1 rounded text-blue-300">{selectedSessionInfo.replay_session_id}</span>
              {sessionLoading && (
                <RefreshCw className="w-3 h-3 animate-spin text-blue-400 ml-2" />
              )}
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm text-gray-400">
              <div>策略: <span className="text-slate-200">{selectedSessionInfo.strategy_type?.toUpperCase()}</span></div>
              <div>币种: <span className="text-slate-200">{selectedSessionInfo.symbol}</span></div>
              <div>周期: <span className="text-slate-200">{selectedSessionInfo.params?.interval || '1h'}</span></div>
              <div>初始资金: <span className="text-green-400">${selectedSessionInfo.initial_capital?.toLocaleString()}</span></div>
            </div>
            <div className="mt-2 text-xs text-gray-500">
              时间范围: {new Date(selectedSessionInfo.start_time).toLocaleString()} ~ {new Date(selectedSessionInfo.end_time).toLocaleString()}
            </div>
          </div>
        )}

        {/* 会话数据加载错误提示 */}
        {sessionError && (
          <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-4 mb-4">
            <p className="text-red-400 text-sm">{sessionError}</p>
          </div>
        )}

        {/* Core Metrics Cards */}
        {selectedSessionId && sessionLoading && !sessionMetrics ? (
          <div className="flex items-center justify-center py-10 text-slate-500">
            <RefreshCw className="w-5 h-5 animate-spin mr-2" />
            <span className="text-sm">加载会话指标中...</span>
          </div>
        ) : (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
          <Card className="bg-gradient-to-br from-slate-900 to-slate-800/50 border-slate-700/50">
            <CardContent className="p-4">
              <div className="flex items-center gap-2 mb-2">
                <Target className="w-4 h-4 text-slate-500" />
                <p className="text-xs text-slate-400">总收益率</p>
              </div>
              <p className={`text-2xl font-bold ${activeMetrics?.total_return == null ? "text-slate-400" : (activeMetrics.total_return >= 0 ? "text-green-400" : "text-red-400")}`}>
                {formatPct(activeMetrics?.total_return, true)}
              </p>
            </CardContent>
          </Card>

          <Card className="bg-gradient-to-br from-slate-900 to-slate-800/50 border-slate-700/50">
            <CardContent className="p-4">
              <div className="flex items-center gap-2 mb-2">
                <TrendingUp className="w-4 h-4 text-slate-500" />
                <p className="text-xs text-slate-400">年化收益率</p>
              </div>
              <p className={`text-2xl font-bold ${activeMetrics?.annualized_return == null ? "text-slate-400" : (activeMetrics.annualized_return >= 0 ? "text-green-400" : "text-red-400")}`}>
                {formatPct(activeMetrics?.annualized_return, true)}
              </p>
            </CardContent>
          </Card>

          <Card className="bg-gradient-to-br from-slate-900 to-slate-800/50 border-slate-700/50">
            <CardContent className="p-4">
              <div className="flex items-center gap-2 mb-2">
                <Zap className="w-4 h-4 text-blue-400" />
                <p className="text-xs text-slate-400">夏普比率</p>
              </div>
              <p className={`text-2xl font-bold ${activeMetrics?.sharpe_ratio == null ? "text-slate-400" : "text-blue-400"}`}>
                {activeMetrics?.sharpe_ratio != null ? activeMetrics.sharpe_ratio.toFixed(2) : "N/A"}
              </p>
            </CardContent>
          </Card>

          <Card className="bg-gradient-to-br from-slate-900 to-slate-800/50 border-slate-700/50">
            <CardContent className="p-4">
              <div className="flex items-center gap-2 mb-2">
                <AlertTriangle className="w-4 h-4 text-red-400" />
                <p className="text-xs text-slate-400">最大回撤</p>
              </div>
              <p className={`text-2xl font-bold ${activeMetrics?.max_drawdown_pct == null ? "text-slate-400" : "text-red-400"}`}>
                {activeMetrics?.max_drawdown_pct != null ? `-${Math.abs(activeMetrics.max_drawdown_pct).toFixed(2)}%` : "N/A"}
              </p>
            </CardContent>
          </Card>

          <Card className="bg-gradient-to-br from-slate-900 to-slate-800/50 border-slate-700/50">
            <CardContent className="p-4">
              <div className="flex items-center gap-2 mb-2">
                <Clock className="w-4 h-4 text-amber-400" />
                <p className="text-xs text-slate-400">回撤持续期</p>
              </div>
              <p className={`text-2xl font-bold ${activeMetrics?.max_drawdown_duration == null ? "text-slate-400" : "text-amber-400"}`}>
                {activeMetrics?.max_drawdown_duration != null ? `${activeMetrics.max_drawdown_duration} 天` : "N/A"}
              </p>
            </CardContent>
          </Card>

          <Card className="bg-gradient-to-br from-slate-900 to-slate-800/50 border-slate-700/50">
            <CardContent className="p-4">
              <div className="flex items-center gap-2 mb-2">
                <Activity className="w-4 h-4 text-purple-400" />
                <p className="text-xs text-slate-400">胜率</p>
              </div>
              <p className={`text-2xl font-bold ${activeMetrics?.win_rate == null ? "text-slate-400" : "text-purple-400"}`}>
                {activeMetrics?.win_rate != null ? `${activeMetrics.win_rate.toFixed(1)}%` : "N/A"}
              </p>
            </CardContent>
          </Card>

          <Card className="bg-gradient-to-br from-slate-900 to-slate-800/50 border-slate-700/50">
            <CardContent className="p-4">
              <div className="flex items-center gap-2 mb-2">
                <DollarSign className="w-4 h-4 text-yellow-400" />
                <p className="text-xs text-slate-400">盈亏比</p>
              </div>
              <p className={`text-2xl font-bold ${activeMetrics?.profit_factor == null ? "text-slate-400" : "text-yellow-400"}`}>
                {activeMetrics?.profit_factor != null ? activeMetrics.profit_factor.toFixed(2) : "N/A"}
              </p>
            </CardContent>
          </Card>

          <Card className="bg-gradient-to-br from-slate-900 to-slate-800/50 border-slate-700/50">
            <CardContent className="p-4">
              <div className="flex items-center gap-2 mb-2">
                <TrendingUp className="w-4 h-4 text-cyan-400" />
                <p className="text-xs text-slate-400">卡玛比率</p>
              </div>
              <p className={`text-2xl font-bold ${activeMetrics?.calmar_ratio == null ? "text-slate-400" : "text-cyan-400"}`}>
                {activeMetrics?.calmar_ratio != null ? activeMetrics.calmar_ratio.toFixed(2) : "N/A"}
              </p>
            </CardContent>
          </Card>

          <Card className="bg-gradient-to-br from-slate-900 to-slate-800/50 border-slate-700/50">
            <CardContent className="p-4">
              <div className="flex items-center gap-2 mb-2">
                <TrendingDown className="w-4 h-4 text-indigo-400" />
                <p className="text-xs text-slate-400">Sortino 比率</p>
              </div>
              <p className={`text-2xl font-bold ${activeMetrics?.sortino_ratio == null ? "text-slate-400" : "text-indigo-400"}`}>
                {activeMetrics?.sortino_ratio != null ? activeMetrics.sortino_ratio.toFixed(2) : "N/A"}
              </p>
            </CardContent>
          </Card>

          <Card className="bg-gradient-to-br from-slate-900 to-slate-800/50 border-slate-700/50">
            <CardContent className="p-4">
              <div className="flex items-center gap-2 mb-2">
                <Activity className="w-4 h-4 text-pink-400" />
                <p className="text-xs text-slate-400">波动率</p>
              </div>
              <p className={`text-2xl font-bold ${activeMetrics?.volatility == null ? "text-slate-400" : "text-pink-400"}`}>
                {activeMetrics?.volatility != null ? `${activeMetrics.volatility.toFixed(2)}%` : "N/A"}
              </p>
            </CardContent>
          </Card>

          <Card className="bg-gradient-to-br from-slate-900 to-slate-800/50 border-slate-700/50">
            <CardContent className="p-4">
              <div className="flex items-center gap-2 mb-2">
                <BarChart3 className="w-4 h-4 text-orange-400" />
                <p className="text-xs text-slate-400">交易次数</p>
              </div>
              <p className={`text-2xl font-bold ${activeMetrics?.total_trades == null ? "text-slate-400" : "text-slate-100"}`}>
                {activeMetrics?.total_trades ?? "N/A"}
              </p>
            </CardContent>
          </Card>

          <Card className="bg-gradient-to-br from-slate-900 to-slate-800/50 border-slate-700/50">
            <CardContent className="p-4">
              <div className="flex items-center gap-2 mb-2">
                <Wallet className="w-4 h-4 text-green-400" />
                <p className="text-xs text-slate-400">当前权益</p>
              </div>
              <p className={`text-2xl font-bold ${activeMetrics?.final_equity == null ? "text-slate-400" : "text-green-400"}`}>
                {formatMoney(activeMetrics?.final_equity, true)}
              </p>
            </CardContent>
          </Card>
        </div>
        )}

        {/* Charts Row */}
        {error && (
          <div className="flex items-center justify-center py-4 text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg">
            <AlertTriangle className="w-4 h-4 mr-2" />
            <span className="text-sm">{error}</span>
          </div>
        )}
        {hasMockDataWarning && !showMockData && (
          <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 mb-4 flex items-start gap-3">
            <AlertTriangle className="w-5 h-5 text-yellow-600 mt-0.5 flex-shrink-0" />
            <div className="flex-1">
              <p className="text-sm font-medium text-yellow-900">当前无真实交易数据</p>
              <p className="text-xs text-yellow-700 mt-1">
                请先运行模拟盘、回测或历史回放，真实数据将自动显示在图表中。
                可在右上角开启"显示演示数据"查看模拟数据。
              </p>
            </div>
            <button
              onClick={() => setShowMockData(true)}
              className="text-xs text-yellow-800 hover:text-yellow-900 underline"
            >
              查看演示数据
            </button>
          </div>
        )}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Equity Curve Chart */}
          <Card className="bg-gradient-to-br from-slate-900 to-slate-800/30 border-slate-700/50">
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-slate-100 text-base flex items-center gap-2">
                  <TrendingUp className="w-4 h-4 text-green-400" />
                  权益曲线
                  {selectedSessionId && sessionEquityData ? (
                    <Badge variant="outline" className="text-[10px] bg-blue-500/10 text-blue-400 border-blue-500/20">
                      回放 vs 回测
                    </Badge>
                  ) : !loading && !error && (
                    <Badge variant="outline" className="text-[10px] bg-green-500/10 text-green-400 border-green-500/20">
                      {chartData.length} 数据点
                    </Badge>
                  )}
                </CardTitle>
              </div>
            </CardHeader>
            <CardContent className="h-[300px]">
              {loading || sessionLoading ? (
                <div className="flex items-center justify-center h-full text-slate-500">
                  <RefreshCw className="w-5 h-5 animate-spin mr-2" /> 加载中...
                </div>
              ) : selectedSessionId && sessionEquityData?.normalized_replay?.length > 0 ? (
                /* 会话模式 - 显示回放 vs 回测双线 */
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart 
                    data={(() => {
                      const replayData = sessionEquityData.normalized_replay || [];
                      const backtestData = sessionEquityData.normalized_backtest || [];
                      const maxLen = Math.max(replayData.length, backtestData.length);
                      const merged = [];
                      for (let i = 0; i < maxLen; i++) {
                        const replayPoint = replayData[i];
                        const backtestPoint = backtestData[i];
                        merged.push({
                          index: i,
                          replay: replayPoint?.return_pct,
                          backtest: backtestPoint?.return_pct,
                        });
                      }
                      return merged;
                    })()}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="index" stroke="#64748b" fontSize={10} tickLine={false} />
                    <YAxis stroke="#64748b" fontSize={10} tickLine={false} tickFormatter={(v) => `${v.toFixed(1)}%`} />
                    <Tooltip
                      contentStyle={{ backgroundColor: "#1e293b", border: "1px solid #334155", borderRadius: "8px" }}
                      labelStyle={{ color: "#94a3b8" }}
                      formatter={(value, name) => [
                        typeof value === "number" ? `${value.toFixed(2)}%` : "N/A", 
                        name === "replay" ? "回放实际收益率" : "回测理论收益率"
                      ]}
                    />
                    <Legend 
                      formatter={(value) => value === "replay" ? "回放实际收益率" : "回测理论收益率"}
                    />
                    <Line 
                      type="monotone" 
                      dataKey="replay" 
                      stroke="#3b82f6" 
                      strokeWidth={2} 
                      dot={false} 
                      name="replay"
                      connectNulls
                    />
                    <Line 
                      type="monotone" 
                      dataKey="backtest" 
                      stroke="#94a3b8" 
                      strokeWidth={2} 
                      strokeDasharray="5 5"
                      dot={false}
                      name="backtest"
                      connectNulls
                    />
                  </LineChart>
                </ResponsiveContainer>
              ) : chartData.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full text-slate-500 text-sm space-y-2">
                  <BarChart3 className="w-12 h-12 opacity-30" />
                  <p>暂无权益数据</p>
                  <p className="text-xs text-slate-600">
                    请先在 <Link href="/dashboard" className="text-blue-400 hover:underline">仪表盘</Link> 进行模拟交易
                  </p>
                </div>
              ) : (
                /* 全局模式 - 显示原有的单线权益曲线 */
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={chartData}>
                    <defs>
                      <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#10b981" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="time" stroke="#64748b" fontSize={10} tickLine={false} />
                    <YAxis stroke="#64748b" fontSize={10} tickLine={false} tickFormatter={(v) => `$${(v/1000).toFixed(0)}k`} />
                    <Tooltip
                      contentStyle={{ backgroundColor: "#1e293b", border: "1px solid #334155", borderRadius: "8px" }}
                      labelStyle={{ color: "#94a3b8" }}
                      formatter={(value: any) => [typeof value === "number" ? `$${value.toFixed(2)}` : `$${value}`, "权益"]}
                    />
                    <Area type="monotone" dataKey="equity" stroke="#10b981" strokeWidth={2} fill="url(#equityGradient)" />
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>

          {/* Drawdown Chart */}
          <Card className="bg-gradient-to-br from-slate-900 to-slate-800/30 border-slate-700/50">
            <CardHeader className="pb-2">
              <CardTitle className="text-slate-100 text-base flex items-center gap-2">
                <TrendingDown className="w-4 h-4 text-red-400" />
                回撤曲线
                {selectedSessionId && sessionEquityData && (
                  <Badge variant="outline" className="text-[10px] bg-blue-500/10 text-blue-400 border-blue-500/20">
                    会话模式
                  </Badge>
                )}
              </CardTitle>
            </CardHeader>
            <CardContent className="h-[300px]">
              {loading || sessionLoading ? (
                <div className="flex items-center justify-center h-full text-slate-500">
                  <RefreshCw className="w-5 h-5 animate-spin mr-2" /> 加载中...
                </div>
              ) : (() => {
                // 确定回撤数据源：会话模式使用会话数据，全局模式使用全局数据
                const drawdownChartData = selectedSessionId && sessionEquityData?.normalized_replay?.length > 0
                  ? sessionEquityData.normalized_replay.map((p: any, idx: number) => ({
                      time: idx,
                      // 回撤应为负值，确保显示为负数（如果后端返回正数则取负）
                      drawdown: p.drawdown_pct != null 
                        ? -Math.abs(p.drawdown_pct) 
                        : (p.drawdown != null ? -Math.abs(p.drawdown) : 0),
                    }))
                  : chartData.map(d => ({
                      ...d,
                      // 确保全局模式回撤也是负值
                      drawdown: d.drawdown != null ? -Math.abs(d.drawdown) : 0,
                    }));
                
                const hasDrawdownData = drawdownChartData.length > 0 && drawdownChartData.some((d: any) => d.drawdown !== 0);
                
                return !hasDrawdownData ? (
                  <div className="flex flex-col items-center justify-center h-full text-slate-500 text-sm space-y-2">
                    <TrendingDown className="w-12 h-12 opacity-30" />
                    <p>暂无回撤数据</p>
                    <p className="text-xs text-slate-600">
                      开始交易后将在此显示回撤曲线
                    </p>
                  </div>
                ) : (
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={drawdownChartData}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                      <XAxis dataKey="time" stroke="#64748b" fontSize={10} tickLine={false} />
                      <YAxis stroke="#64748b" fontSize={10} tickLine={false} domain={['auto', 0]} tickFormatter={(v) => `${typeof v === 'number' ? v.toFixed(1) : v}%`} />
                      <Tooltip
                        contentStyle={{ backgroundColor: "#1e293b", border: "1px solid #334155", borderRadius: "8px" }}
                        labelStyle={{ color: "#94a3b8" }}
                        formatter={(value: any) => [typeof value === "number" ? `${value.toFixed(2)}%` : `${value}`, "回撤"]}
                      />
                      <Line type="monotone" dataKey="drawdown" stroke="#ef4444" strokeWidth={2} dot={false} name="回撤 (%)" />
                    </LineChart>
                  </ResponsiveContainer>
                );
              })()}
            </CardContent>
          </Card>
        </div>

        {/* 交易记录区域 - Session Trades Table */}
        {selectedSessionId && sessionTrades.length > 0 ? (
          <Card className="bg-gradient-to-br from-slate-900 to-slate-800/30 border-slate-700/50">
            <CardHeader className="pb-2">
              <CardTitle className="text-slate-100 text-base flex items-center gap-2">
                <Activity className="w-4 h-4 text-cyan-400" />
                交易记录
                <Badge variant="outline" className="text-[10px] bg-cyan-500/10 text-cyan-400 border-cyan-500/20">
                  {sessionTrades.length} 笔
                </Badge>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-gray-400 border-b border-gray-700">
                      <th className="text-left py-2 font-medium">时间</th>
                      <th className="text-left py-2 font-medium">方向</th>
                      <th className="text-right py-2 font-medium">价格</th>
                      <th className="text-right py-2 font-medium">数量</th>
                      <th className="text-right py-2 font-medium">盈亏</th>
                      <th className="text-right py-2 font-medium">手续费</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sessionTrades.slice(0, 50).map((trade, idx) => (
                      <tr key={trade.trade_id || idx} className="border-b border-gray-800 hover:bg-slate-800/30">
                        <td className="py-2 text-gray-300">{safeFormatDate(trade.created_at)}</td>
                        <td className={`py-2 font-medium ${trade.side === 'BUY' ? 'text-green-400' : 'text-red-400'}`}>
                          {trade.side}
                        </td>
                        <td className="py-2 text-right text-gray-300 font-mono">
                          ${trade.price?.toFixed(2)}
                        </td>
                        <td className="py-2 text-right text-gray-300 font-mono">
                          {trade.quantity?.toFixed(6)}
                        </td>
                        <td className={`py-2 text-right font-mono font-medium ${
                          trade.pnl == null ? 'text-gray-500' : 
                          trade.pnl >= 0 ? 'text-green-400' : 'text-red-400'
                        }`}>
                          {trade.pnl != null ? `${trade.pnl >= 0 ? '+' : ''}${trade.pnl.toFixed(2)}` : '-'}
                        </td>
                        <td className="py-2 text-right text-gray-400 font-mono">
                          {trade.fee?.toFixed(4) || '-'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {sessionTrades.length > 50 && (
                <p className="text-xs text-slate-500 text-center mt-3">
                  显示前 50 条记录，共 {sessionTrades.length} 笔交易
                </p>
              )}
            </CardContent>
          </Card>
        ) : selectedSessionId ? (
          <Card className="bg-gradient-to-br from-slate-900 to-slate-800/30 border-slate-700/50">
            <CardContent className="py-8">
              <div className="flex flex-col items-center justify-center text-slate-500 gap-2">
                <Activity className="w-8 h-8 opacity-40" />
                <p className="text-sm">暂无交易记录</p>
                <p className="text-xs text-slate-600">该回放会话尚未产生交易</p>
              </div>
            </CardContent>
          </Card>
        ) : (
          <Card className="bg-gradient-to-br from-slate-900 to-slate-800/30 border-slate-700/50">
            <CardContent className="py-8">
              <div className="flex flex-col items-center justify-center text-slate-500 gap-2">
                <Activity className="w-8 h-8 opacity-40" />
                <p className="text-sm">请选择回放会话查看交易明细</p>
                <p className="text-xs text-slate-600">在页面顶部的「查看会话」下拉框中选择一个已完成的回放会话</p>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Strategy Attribution & Comparison Row */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Profit Attribution Pie Chart */}
          <Card className="bg-gradient-to-br from-slate-900 to-slate-800/30 border-slate-700/50">
            <CardHeader className="pb-2">
              <CardTitle className="text-slate-100 text-base flex items-center gap-2">
                <PieChartIcon className="w-4 h-4 text-purple-400" />
                策略收益归因 (Attribution)
              </CardTitle>
            </CardHeader>
            <CardContent className="h-[300px]">
              {loading ? (
                <div className="flex items-center justify-center h-full text-slate-500">
                  <RefreshCw className="w-5 h-5 animate-spin mr-2" /> 加载中...
                </div>
              ) : attribution.length === 0 ? (
                <div className="flex items-center justify-center h-full text-slate-500 text-sm">
                  暂无归因数据，需要完成至少一笔交易
                </div>
              ) : (
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={attribution}
                      dataKey="total_pnl"
                      nameKey="strategy_id"
                      cx="50%"
                      cy="50%"
                      outerRadius={90}
                      innerRadius={40}
                      paddingAngle={2}
                    >
                      {attribution.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={STRATEGY_COLORS[index % STRATEGY_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{ backgroundColor: "#1e293b", border: "1px solid #334155", borderRadius: "8px" }}
                      labelStyle={{ color: "#94a3b8" }}
                      formatter={(value: any) => [typeof value === "number" ? `$${value.toFixed(2)}` : `$${value}`, "累计盈亏"]}
                    />
                  </PieChart>
                </ResponsiveContainer>
              )}
              {/* 简化图例 */}
              {attribution.length > 0 && (
                <div className="mt-2 flex flex-wrap justify-center gap-x-3 gap-y-1 max-h-16 overflow-y-auto">
                  {attribution.slice(0, 8).map((entry, index) => (
                    <div key={entry.strategy_id} className="flex items-center gap-1 text-[10px]">
                      <div className="w-2 h-2 rounded-full" style={{ backgroundColor: STRATEGY_COLORS[index % STRATEGY_COLORS.length] }} />
                      <span className="text-slate-400">{entry.strategy_id}</span>
                    </div>
                  ))}
                  {attribution.length > 8 && (
                    <span className="text-slate-500 text-[10px]">+{attribution.length - 8} 更多</span>
                  )}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Strategy Comparison Bar Chart */}
          <Card className="bg-gradient-to-br from-slate-900 to-slate-800/30 border-slate-700/50">
            <CardHeader className="pb-2">
              <CardTitle className="text-slate-100 text-base flex items-center gap-2">
                <Activity className="w-4 h-4 text-blue-400" />
                模拟盘 vs 回测表现对比
              </CardTitle>
            </CardHeader>
            <CardContent className="h-[300px]">
              {loading ? (
                <div className="flex items-center justify-center h-full text-slate-500">
                  <RefreshCw className="w-5 h-5 animate-spin mr-2" /> 加载中...
                </div>
              ) : comparison.length === 0 ? (
                <div className="flex items-center justify-center h-full text-slate-500 text-sm">
                  暂无对比数据
                </div>
              ) : (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={comparison.map(c => ({
                    name: c.strategy_name,
                    "模拟盘 PnL": c.paper.total_pnl,
                    "回测收益率": c.backtest?.total_return || 0
                  }))}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="name" stroke="#64748b" fontSize={10} />
                    <YAxis stroke="#64748b" fontSize={10} />
                    <Tooltip
                      contentStyle={{ backgroundColor: "#1e293b", border: "1px solid #334155", borderRadius: "8px" }}
                    />
                    <Legend />
                    <Bar dataKey="模拟盘 PnL" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="回测收益率" fill="#10b981" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Strategy Attribution Detail - 增强归因分析 */}
        <Card className="bg-gradient-to-br from-slate-900 to-slate-800/30 border-slate-700/50">
          <CardHeader className="pb-2 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
            <CardTitle className="text-slate-100 text-base flex items-center gap-2">
              <Target className="w-4 h-4 text-orange-400" />
              增强归因分析 (Enhanced Attribution)
            </CardTitle>
            <div className="flex items-center gap-3 flex-wrap">
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-400 hidden sm:inline">数据模式:</span>
                <select 
                  className="bg-slate-800 border border-slate-700 text-slate-200 text-xs rounded p-1.5"
                  value={attrMode}
                  onChange={(e) => {
                    setAttrMode(e.target.value);
                    if (e.target.value !== "historical_replay") {
                      setAttrSessionId("");
                    }
                  }}
                >
                  <option value="backtest">回测 (Backtest)</option>
                  <option value="historical_replay">历史回放 (Replay)</option>
                  <option value="paper">模拟盘 (Paper)</option>
                </select>
              </div>
              
              {attrMode === "historical_replay" && (
                <div className="flex items-center gap-2">
                  <span className="text-xs text-slate-400">回放会话:</span>
                  <select 
                    className="bg-slate-800 border border-slate-700 text-slate-200 text-xs rounded p-1.5 max-w-[200px]"
                    value={attrSessionId}
                    onChange={(e) => setAttrSessionId(e.target.value)}
                  >
                    <option value="">自动选择最新</option>
                    {completedReplaySessions.map(s => (
                      <option key={s.replay_session_id} value={s.replay_session_id}>
                    {s.symbol} / {s.strategy_type} ({safeFormatDateShort(s.created_at)})
                      </option>
                    ))}
                  </select>
                </div>
              )}

              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-400 hidden sm:inline">策略:</span>
                <select 
                  className="bg-slate-800 border border-slate-700 text-slate-200 text-xs rounded p-1.5"
                  value={selectedStrategy}
                  onChange={(e) => setSelectedStrategy(e.target.value)}
                >
                  <option value="auto_trend_ma">MA Cross</option>
                  <option value="auto_reversion_rsi">RSI</option>
                  <option value="auto_volatility_boll">BOLL</option>
                </select>
              </div>
              
              <Button 
                variant="ghost" 
                size="sm" 
                className="h-8 text-xs text-slate-400 hover:text-slate-100"
                onClick={fetchEnhancedAttribution}
                disabled={enhancedAttrLoading}
              >
                <RefreshCw className={`w-3 h-3 mr-1 ${enhancedAttrLoading ? "animate-spin" : ""}`} /> 刷新
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            {enhancedAttrLoading ? (
              <div className="flex items-center justify-center h-[200px] text-slate-500">
                <RefreshCw className="w-5 h-5 animate-spin mr-2" /> 加载增强归因数据中...
              </div>
            ) : enhancedAttribution?.error ? (
              <div className="flex flex-col items-center justify-center h-[200px] text-slate-400 gap-3">
                <AlertTriangle className="w-8 h-8 text-yellow-400 opacity-70" />
                <p className="text-sm text-yellow-400">{enhancedAttribution.message || '归因分析暂不可用'}</p>
                <p className="text-[10px] text-slate-500 max-w-md text-center">
                  {enhancedAttribution.error || '请确保已运行过相关模式的交易（回测/历史回放/模拟盘）'}
                </p>
                <button 
                  onClick={() => fetchEnhancedAttribution()}
                  className="mt-2 text-xs text-blue-400 hover:text-blue-300 underline"
                >
                  重试
                </button>
              </div>
            ) : enhancedAttribution?.trades?.length > 0 ? (
              <div className="space-y-4">
                {/* 汇总统计卡片 */}
                <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
                  <div className="p-3 bg-slate-800/30 rounded-lg border border-slate-700/30">
                    <p className="text-[10px] text-slate-500 uppercase">总滑点影响</p>
                    <p className={`text-lg font-bold ${(enhancedAttribution.summary?.total_slippage_impact || 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                      {formatMoney(enhancedAttribution.summary?.total_slippage_impact, true)}
                    </p>
                  </div>
                  <div className="p-3 bg-slate-800/30 rounded-lg border border-slate-700/30">
                    <p className="text-[10px] text-slate-500 uppercase">总延迟影响</p>
                    <p className={`text-lg font-bold ${(enhancedAttribution.summary?.total_latency_impact || 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                      {formatMoney(enhancedAttribution.summary?.total_latency_impact, true)}
                    </p>
                  </div>
                  <div className="p-3 bg-slate-800/30 rounded-lg border border-slate-700/30">
                    <p className="text-[10px] text-slate-500 uppercase">平均执行质量</p>
                    <p className={`text-lg font-bold ${
                      (enhancedAttribution.summary?.avg_execution_quality || 0) >= 80 ? "text-green-400" : 
                      (enhancedAttribution.summary?.avg_execution_quality || 0) >= 50 ? "text-yellow-400" : "text-red-400"
                    }`}>
                      {enhancedAttribution.summary?.avg_execution_quality != null 
                        ? `${enhancedAttribution.summary.avg_execution_quality.toFixed(1)}%` 
                        : "N/A"}
                    </p>
                  </div>
                  <div className="p-3 bg-slate-800/30 rounded-lg border border-slate-700/30">
                    <p className="text-[10px] text-slate-500 uppercase">平均时间差</p>
                    <p className="text-lg font-bold text-slate-300">
                      {enhancedAttribution.summary?.avg_timing_diff != null 
                        ? `${enhancedAttribution.summary.avg_timing_diff.toFixed(1)}秒` 
                        : "N/A"}
                    </p>
                  </div>
                  <div className="p-3 bg-slate-800/30 rounded-lg border border-slate-700/30">
                    <p className="text-[10px] text-slate-500 uppercase">总手续费影响</p>
                    <p className={`text-lg font-bold ${(enhancedAttribution.summary?.total_fee_impact || 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                      {formatMoney(enhancedAttribution.summary?.total_fee_impact, true)}
                    </p>
                  </div>
                  <div className="p-3 bg-slate-800/30 rounded-lg border border-slate-700/30">
                    <p className="text-[10px] text-slate-500 uppercase">交易笔数</p>
                    <p className="text-lg font-bold text-slate-100">
                      {enhancedAttribution.trades?.length ?? 0}
                    </p>
                  </div>
                </div>

                {/* 增强归因表格 */}
                <div className="overflow-x-auto">
                  <table className="w-full text-xs text-left">
                    <thead>
                      <tr className="text-slate-500 border-b border-slate-800">
                        <th className="pb-2 font-medium whitespace-nowrap">时间</th>
                        <th className="pb-2 font-medium">品种</th>
                        <th className="pb-2 font-medium text-right">价格差异</th>
                        <th className="pb-2 font-medium text-right">滑点影响</th>
                        <th className="pb-2 font-medium text-right">延迟影响</th>
                        <th className="pb-2 font-medium text-right">手续费影响</th>
                        <th className="pb-2 font-medium text-center">执行质量</th>
                        <th className="pb-2 font-medium text-right">时间差</th>
                      </tr>
                    </thead>
                    <tbody className="text-slate-300">
                      {enhancedAttribution.trades?.slice(0, 20).map((t: any, idx: number) => (
                        <tr key={idx} className="border-b border-slate-800/50 hover:bg-slate-800/20">
                          <td className="py-2 text-slate-400 whitespace-nowrap">
                            {t.timestamp ? safeFormatDate(t.timestamp) : "-"}
                          </td>
                          <td className="py-2">
                            <Badge variant="outline" className="text-blue-400 border-blue-500/20">
                              {t.symbol || "-"}
                            </Badge>
                          </td>
                          <td className={`py-2 text-right font-mono ${(t.delta_price || 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                            {formatMoney(t.delta_price, true)}
                          </td>
                          <td className={`py-2 text-right font-mono ${(t.slippage_impact || 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                            {formatMoney(t.slippage_impact, true)}
                          </td>
                          <td className={`py-2 text-right font-mono ${(t.latency_impact || 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                            {formatMoney(t.latency_impact, true)}
                          </td>
                          <td className={`py-2 text-right font-mono ${(t.fee_impact || 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                            {formatMoney(t.fee_impact, true)}
                          </td>
                          <td className="py-2 text-center">
                            {t.execution_quality != null ? (
                              <Badge 
                                variant="outline" 
                                className={`${
                                  t.execution_quality >= 80 ? "bg-green-500/10 text-green-400 border-green-500/20" :
                                  t.execution_quality >= 50 ? "bg-yellow-500/10 text-yellow-400 border-yellow-500/20" :
                                  "bg-red-500/10 text-red-400 border-red-500/20"
                                }`}
                              >
                                {t.execution_quality.toFixed(0)}%
                              </Badge>
                            ) : (
                              <span className="text-slate-500">N/A</span>
                            )}
                          </td>
                          <td className="py-2 text-right font-mono text-slate-400">
                            {t.timing_diff != null ? `${t.timing_diff.toFixed(1)}秒` : "N/A"}
                          </td>
                        </tr>
                      ))}
                      {/* 汇总行 */}
                      {enhancedAttribution.summary && (
                        <tr className="border-t-2 border-slate-700 bg-slate-800/30 font-semibold">
                          <td className="py-3 text-slate-300" colSpan={2}>汇总</td>
                          <td className={`py-3 text-right font-mono ${(enhancedAttribution.summary.total_delta_price || 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                            {formatMoney(enhancedAttribution.summary.total_delta_price, true)}
                          </td>
                          <td className={`py-3 text-right font-mono ${(enhancedAttribution.summary.total_slippage_impact || 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                            {formatMoney(enhancedAttribution.summary.total_slippage_impact, true)}
                          </td>
                          <td className={`py-3 text-right font-mono ${(enhancedAttribution.summary.total_latency_impact || 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                            {formatMoney(enhancedAttribution.summary.total_latency_impact, true)}
                          </td>
                          <td className={`py-3 text-right font-mono ${(enhancedAttribution.summary.total_fee_impact || 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                            {formatMoney(enhancedAttribution.summary.total_fee_impact, true)}
                          </td>
                          <td className="py-3 text-center">
                            <Badge 
                              variant="outline" 
                              className={`${
                                (enhancedAttribution.summary.avg_execution_quality || 0) >= 80 ? "bg-green-500/10 text-green-400 border-green-500/20" :
                                (enhancedAttribution.summary.avg_execution_quality || 0) >= 50 ? "bg-yellow-500/10 text-yellow-400 border-yellow-500/20" :
                                "bg-red-500/10 text-red-400 border-red-500/20"
                              }`}
                            >
                              平均 {enhancedAttribution.summary.avg_execution_quality?.toFixed(0) ?? "N/A"}%
                            </Badge>
                          </td>
                          <td className="py-3 text-right font-mono text-slate-300">
                            平均 {enhancedAttribution.summary.avg_timing_diff?.toFixed(1) ?? "N/A"}秒
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>

                {enhancedAttribution.trades?.length > 20 && (
                  <p className="text-xs text-slate-500 text-center">
                    显示前 20 条记录，共 {enhancedAttribution.trades.length} 条
                  </p>
                )}
              </div>
            ) : strategyAttribution && strategyAttribution.global ? (
              <div className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
                  {/* Waterfall Chart Simulation */}
                  <div className="h-[300px] bg-slate-800/20 p-4 rounded-xl border border-slate-700/30">
                    <p className="text-sm font-medium text-slate-300 mb-4">总体归因瀑布图 (Global Attribution)</p>
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart
                        data={[
                          { name: '回测收益', value: strategyAttribution.global.bt_total_pnl || 0, fill: '#64748b' },
                          { name: '价格差异', value: strategyAttribution.global.delta_price || 0, fill: (strategyAttribution.global.delta_price || 0) >= 0 ? '#10b981' : '#ef4444' },
                          { name: '成交率', value: strategyAttribution.global.delta_fill || 0, fill: (strategyAttribution.global.delta_fill || 0) >= 0 ? '#10b981' : '#ef4444' },
                          { name: '手续费', value: strategyAttribution.global.delta_fees || 0, fill: (strategyAttribution.global.delta_fees || 0) >= 0 ? '#10b981' : '#ef4444' },
                          { name: '模拟收益', value: strategyAttribution.global.sim_total_pnl || 0, fill: '#3b82f6' },
                        ]}
                      >
                        <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
                        <XAxis dataKey="name" stroke="#64748b" fontSize={10} />
                        <YAxis stroke="#64748b" fontSize={10} />
                        <Tooltip
                          contentStyle={{ backgroundColor: "#1e293b", border: "1px solid #334155", borderRadius: "8px" }}
                          formatter={(v: any) => [`$${Number(v || 0).toFixed(2)}`, "金额"]}
                        />
                        <Bar dataKey="value" radius={[4, 4, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>

                  {/* Daily Stacked Bar Chart */}
                  <div className="h-[300px] bg-slate-800/20 p-4 rounded-xl border border-slate-700/30">
                    <p className="text-sm font-medium text-slate-300 mb-4">每日差异时间序列堆积图 (Daily Diff)</p>
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={strategyAttribution.daily || []}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
                        <XAxis dataKey="date" stroke="#64748b" fontSize={10} />
                        <YAxis stroke="#64748b" fontSize={10} />
                        <Tooltip
                          contentStyle={{ backgroundColor: "#1e293b", border: "1px solid #334155", borderRadius: "8px" }}
                        />
                        <Legend iconType="circle" />
                        <Bar dataKey="delta_price" name="价格差异" stackId="a" fill="#3b82f6" />
                        <Bar dataKey="delta_fill" name="成交率差异" stackId="a" fill="#8b5cf6" />
                        <Bar dataKey="delta_fees" name="手续费差异" stackId="a" fill="#10b981" />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                  <div className="p-3 bg-slate-800/30 rounded-lg border border-slate-700/30">
                    <p className="text-[10px] text-slate-500 uppercase">价格差异 (Delta Price)</p>
                    <p className={`text-lg font-bold ${(strategyAttribution.global.delta_price || 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                      {formatMoney(strategyAttribution.global.delta_price)}
                    </p>
                  </div>
                  <div className="p-3 bg-slate-800/30 rounded-lg border border-slate-700/30">
                    <p className="text-[10px] text-slate-500 uppercase">成交率差异 (Delta Fill)</p>
                    <p className={`text-lg font-bold ${(strategyAttribution.global.delta_fill || 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                      {formatMoney(strategyAttribution.global.delta_fill)}
                    </p>
                  </div>
                  <div className="p-3 bg-slate-800/30 rounded-lg border border-slate-700/30">
                    <p className="text-[10px] text-slate-500 uppercase">手续费差异 (Delta Fees)</p>
                    <p className={`text-lg font-bold ${(strategyAttribution.global.delta_fees || 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                      {formatMoney(strategyAttribution.global.delta_fees)}
                    </p>
                  </div>
                  <div className="p-3 bg-slate-800/30 rounded-lg border border-slate-700/30">
                    <p className="text-[10px] text-slate-500 uppercase">总差异 (Delta Total)</p>
                    <p className={`text-lg font-bold ${(strategyAttribution.global.delta_total || 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                      {formatMoney(strategyAttribution.global.delta_total)}
                    </p>
                  </div>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-100 text-xs text-left">
                    <thead>
                      <tr className="text-slate-500 border-b border-slate-800">
                        <th className="pb-2 font-medium">时间 (Time)</th>
                        <th className="pb-2 font-medium">品种</th>
                        <th className="pb-2 font-medium">回测价</th>
                        <th className="pb-2 font-medium">模拟价</th>
                        <th className="pb-2 font-medium text-right">价格差异</th>
                        <th className="pb-2 font-medium text-right">成交差异</th>
                        <th className="pb-2 font-medium text-right">手续费差异</th>
                        <th className="pb-2 font-medium text-right">总差异</th>
                      </tr>
                    </thead>
                    <tbody className="text-slate-300">
                      {strategyAttribution.trades?.slice(0, 15).map((t: any, idx: number) => (
                        <tr key={idx} className="border-b border-slate-800/50 hover:bg-slate-800/20">
                          <td className="py-2 text-slate-400 whitespace-nowrap">{safeFormatDate(t.timestamp)}</td>
                          <td className="py-2">
                            <Badge variant="outline" className="text-blue-400 border-blue-500/20">
                              {t.symbol}
                            </Badge>
                          </td>
                          <td className="py-2 font-mono">${t.bt_price.toFixed(2)}</td>
                          <td className="py-2 font-mono">${t.sim_price.toFixed(2)}</td>
                          <td className={`py-2 text-right font-mono ${t.delta_price >= 0 ? "text-green-400" : "text-red-400"}`}>
                            {formatMoney(t.delta_price)}
                          </td>
                          <td className={`py-2 text-right font-mono ${t.delta_fill >= 0 ? "text-green-400" : "text-red-400"}`}>
                            {formatMoney(t.delta_fill)}
                          </td>
                          <td className={`py-2 text-right font-mono ${t.delta_fees >= 0 ? "text-green-400" : "text-red-400"}`}>
                            {formatMoney(t.delta_fees)}
                          </td>
                          <td className={`py-2 text-right font-bold font-mono ${t.delta_total >= 0 ? "text-green-400" : "text-red-400"}`}>
                            {formatMoney(t.delta_total)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : (
              <div className="flex items-center justify-center h-[200px] text-slate-500 text-sm">
                加载归因数据中...
              </div>
            )}
          </CardContent>
        </Card>

        {/* Additional Stats Row */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <Card className="bg-gradient-to-br from-slate-900 to-slate-800/30 border-slate-700/50">
            <CardHeader className="pb-2">
              <CardTitle className="text-slate-100 text-base">交易统计</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 gap-4">
                <div className="p-3 bg-slate-800/50 rounded-lg">
                  <p className="text-xs text-slate-400 mb-1">盈利交易</p>
                  <p className="text-lg font-bold text-green-400">{activeMetrics?.winning_trades || 0}</p>
                </div>
                <div className="p-3 bg-slate-800/50 rounded-lg">
                  <p className="text-xs text-slate-400 mb-1">亏损交易</p>
                  <p className="text-lg font-bold text-red-400">{activeMetrics?.losing_trades || 0}</p>
                </div>
                <div className="p-3 bg-slate-800/50 rounded-lg">
                  <p className="text-xs text-slate-400 mb-1">平均盈利</p>
                  <p className="text-lg font-bold text-green-400">{formatMoney(activeMetrics?.avg_profit)}</p>
                </div>
                <div className="p-3 bg-slate-800/50 rounded-lg">
                  <p className="text-xs text-slate-400 mb-1">平均亏损</p>
                  <p className="text-lg font-bold text-red-400">{formatMoney(activeMetrics?.avg_loss)}</p>
                </div>
                <div className="p-3 bg-slate-800/50 rounded-lg">
                  <p className="text-xs text-slate-400 mb-1">最大连续盈利</p>
                  <p className="text-lg font-bold text-purple-400">{activeMetrics?.max_consecutive_wins || 0} 笔</p>
                </div>
                <div className="p-3 bg-slate-800/50 rounded-lg">
                  <p className="text-xs text-slate-400 mb-1">最大连续亏损</p>
                  <p className="text-lg font-bold text-orange-400">{activeMetrics?.max_consecutive_losses || 0} 笔</p>
                </div>
                <div className="p-3 bg-slate-800/50 rounded-lg">
                  <p className="text-xs text-slate-400 mb-1">Sortino比率</p>
                  <p className="text-lg font-bold text-blue-400">{(activeMetrics?.sortino_ratio || 0).toFixed(2)}</p>
                </div>
                <div className="p-3 bg-slate-800/50 rounded-lg">
                  <p className="text-xs text-slate-400 mb-1">年化波动率</p>
                  <p className="text-lg font-bold text-slate-300">{(activeMetrics?.volatility || 0).toFixed(2)}%</p>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Portfolio Exposure */}
          <Card className="bg-gradient-to-br from-slate-900 to-slate-800/30 border-slate-700/50">
            <CardHeader className="pb-2">
              <CardTitle className="text-slate-100 text-base flex items-center gap-2">
                <PieChartIcon className="w-4 h-4 text-blue-400" />
                资产配置与风险暴露
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div className="p-3 bg-slate-800/50 rounded-lg">
                    <p className="text-xs text-slate-400 mb-1">总权益</p>
                    <p className="text-lg font-bold text-green-400">{formatMoney(portfolio?.total_equity)}</p>
                  </div>
                  <div className="p-3 bg-slate-800/50 rounded-lg">
                    <p className="text-xs text-slate-400 mb-1">现金占比</p>
                    <p className="text-lg font-bold text-slate-300">{(portfolio?.cash_pct || 100).toFixed(1)}%</p>
                  </div>
                </div>

                <div className="p-3 bg-slate-800/50 rounded-lg">
                  <p className="text-xs text-slate-400 mb-2">风险暴露</p>
                  <div className="flex items-center justify-between text-sm mb-2">
                    <span className="text-green-400">多頭: ${(portfolio?.exposure.long || 0).toFixed(2)}</span>
                    <span className="text-red-400">空頭: ${(portfolio?.exposure.short || 0).toFixed(2)}</span>
                  </div>
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-slate-400">净暴露: ${(portfolio?.exposure.net_exposure || 0).toFixed(2)}</span>
                    <span className="text-blue-400">杠杆: {(portfolio?.exposure.leverage || 0).toFixed(2)}x</span>
                  </div>
                </div>

                {portfolio && portfolio.asset_allocation.length > 0 && (
                  <div className="p-3 bg-slate-800/50 rounded-lg">
                    <p className="text-xs text-slate-400 mb-2">持仓分布</p>
                    <div className="space-y-2">
                      {portfolio.asset_allocation.slice(0, 5).map((asset, idx) => (
                        <div key={idx} className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <Badge
                              variant="outline"
                              className={`text-[10px] ${asset.side === "LONG"
                                ? "bg-green-500/10 text-green-400 border-green-500/20"
                                : "bg-red-500/10 text-red-400 border-red-500/20"
                              }`}
                            >
                              {asset.side}
                            </Badge>
                            <span className="text-sm text-slate-300">{asset.symbol}</span>
                          </div>
                          <span className="text-sm text-slate-400">{asset.allocation_pct.toFixed(1)}%</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* ── Replay vs Backtest Comparison Section ── */}
        <div className="space-y-6">
          <Card className="bg-gradient-to-br from-slate-900 to-slate-800/30 border-slate-700/50">
            <CardHeader className="pb-2 flex flex-row items-center justify-between">
              <div className="flex items-center gap-2">
                <CardTitle className="text-slate-100 text-base flex items-center gap-2">
                  <Activity className="w-4 h-4 text-cyan-400" />
                  回放 vs 回测 对比分析
                </CardTitle>
                <DataSourceBadge source="REPLAY" />
              </div>
              <div className="flex items-center gap-4">
                <div className="flex items-center gap-2">
                  <span className="text-xs text-slate-400">选择回放会话:</span>
                  <select 
                    className="bg-slate-800 border border-slate-700 text-slate-200 text-xs rounded p-1.5 min-w-[280px]"
                    value={selectedRbSession}
                    onChange={(e) => setSelectedRbSession(e.target.value)}
                  >
                    <option value="">自动选择最新</option>
                    {completedReplaySessions.map(s => {
                      const returnPct = s.total_return != null ? s.total_return.toFixed(2) : null;
                      const returnColor = s.total_return >= 0 ? '↑' : '↓';
                      return (
                        <option key={s.replay_session_id} value={s.replay_session_id}>
                          {s.symbol} / {s.strategy_type} | {safeFormatDateShort(s.created_at)} {returnPct != null ? `| ${returnColor}${returnPct}%` : ''}
                        </option>
                      );
                    })}
                  </select>
                </div>
                <Button 
                  variant="outline" 
                  size="sm" 
                  className="h-8 text-xs border-cyan-500/30 text-cyan-400 hover:bg-cyan-500/10"
                  onClick={() => fetchRbComparison(selectedRbSession)}
                  disabled={rbComparisonLoading}
                >
                  <RefreshCw className={`w-3 h-3 mr-1 ${rbComparisonLoading ? "animate-spin" : ""}`} />
                  刷新
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              {rbComparisonLoading ? (
                <div className="flex flex-col items-center justify-center h-[200px] text-slate-500 gap-3">
                  <RefreshCw className="w-6 h-6 animate-spin" />
                  <p className="text-sm">加载对比数据中...</p>
                </div>
              ) : rbComparison?.error ? (
                <div className="flex flex-col items-center justify-center h-[250px] text-slate-400 gap-4">
                  <div className="w-16 h-16 rounded-full bg-slate-800/50 flex items-center justify-center">
                    <AlertTriangle className="w-8 h-8 text-orange-400" />
                  </div>
                  <div className="text-center">
                    <p className="text-sm font-medium text-slate-300 mb-1">
                      {rbComparison.error.includes('404') || rbComparison.error.includes('暂无') 
                        ? '暂无对比数据' 
                        : '数据加载失败'}
                    </p>
                    <p className="text-xs text-slate-500 max-w-sm">
                      {rbComparison.error.includes('404') || rbComparison.error.includes('暂无')
                        ? '请先运行历史回放后再查看对比分析'
                        : '网络连接失败，请检查后端服务是否运行'}
                    </p>
                  </div>
                  <Button 
                    variant="outline" 
                    size="sm" 
                    className="h-8 text-xs border-slate-600 text-slate-400 hover:text-slate-100"
                    onClick={() => fetchRbComparison(selectedRbSession)}
                  >
                    <RefreshCw className="w-3 h-3 mr-1" /> 重试
                  </Button>
                </div>
              ) : rbComparison?.comparisons?.length > 0 ? (
                <div className="space-y-4">
                  {/* Replay Session Info */}
                  {rbComparison.replay_session && (
                    <div className="flex items-center gap-4 p-3 bg-slate-800/30 rounded-lg border border-slate-700/30">
                      <Badge variant="outline" className="bg-indigo-500/10 text-indigo-400 border-indigo-500/20">
                        历史回放
                      </Badge>
                      <span className="text-sm text-slate-300">
                        {rbComparison.replay_session.symbol} / {rbComparison.replay_session.strategy_type}
                      </span>
                      <span className="text-xs text-slate-500">
                        {safeFormatDateShort(rbComparison.replay_session.start_time)} ~ {safeFormatDateShort(rbComparison.replay_session.end_time)}
                      </span>
                    </div>
                  )}

                  {/* Param diff warning */}
                  {rbComparison.param_diff && Object.keys(rbComparison.param_diff).length > 0 && (
                    <div className="mb-4 p-3 bg-slate-800/30 border border-slate-700/50 rounded-lg">
                      <p className="text-xs font-medium text-slate-300 mb-2">参数差异说明</p>
                      <div className="flex flex-wrap gap-2">
                        {Object.entries(rbComparison.param_diff).map(([key, vals]: [string, any]) => {
                          const isOneSideMissing = vals.replay === "未记录" || vals.backtest === "未记录";
                          return (
                            <span key={key} className={`text-xs px-2 py-1 rounded border ${
                              isOneSideMissing 
                                ? 'bg-slate-700/30 border-slate-600 text-slate-400'  // 柔和样式
                                : 'bg-red-500/10 border-red-500/20 text-red-400'     // 警告样式
                            }`}>
                              <span className="font-medium">{key}:</span>{' '}
                              回放={String(vals.replay)} vs 回测={String(vals.backtest)}
                            </span>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {/* Equity Curve Overlay - 增强版 */}
                  {rbEquityData && (rbEquityData.replay_equity?.length > 0 || rbEquityData.backtest_equity?.length > 0) && (
                    <div className="h-[350px] bg-slate-800/20 p-4 rounded-xl border border-slate-700/30">
                      <p className="text-sm font-medium text-slate-300 mb-4 flex items-center gap-2">
                        <TrendingUp className="w-4 h-4 text-cyan-400" />
                        权益曲线叠加对比
                        <Badge variant="outline" className="text-[10px] bg-slate-700/50 text-slate-400 border-slate-600">
                          深色区域 = 回放与回测差异
                        </Badge>
                      </p>
                      <ResponsiveContainer width="100%" height="85%">
                        <AreaChart 
                          data={(() => {
                            // 合并数据并计算差异
                            const replayData = rbEquityData.replay_equity || [];
                            const backtestData = rbEquityData.backtest_equity || [];
                            const maxLen = Math.max(replayData.length, backtestData.length);
                            const merged = [];
                            for (let i = 0; i < maxLen; i++) {
                              const replayPoint = replayData[i];
                              const backtestPoint = backtestData[i];
                              merged.push({
                                time: replayPoint?.time || backtestPoint?.time || i,
                                replay_equity: replayPoint?.equity ?? null,
                                backtest_equity: backtestPoint?.equity ?? null,
                                diff: (replayPoint?.equity != null && backtestPoint?.equity != null) 
                                  ? replayPoint.equity - backtestPoint.equity 
                                  : null,
                              });
                            }
                            return merged;
                          })()}
                        >
                          <defs>
                            <linearGradient id="diffGradientPos" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="5%" stopColor="#10b981" stopOpacity={0.3} />
                              <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                            </linearGradient>
                            <linearGradient id="diffGradientNeg" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="5%" stopColor="#ef4444" stopOpacity={0.3} />
                              <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
                            </linearGradient>
                          </defs>
                          <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                          <XAxis dataKey="time" stroke="#64748b" fontSize={10} />
                          <YAxis stroke="#64748b" fontSize={10} tickFormatter={(v) => `$${(v/1000).toFixed(0)}k`} />
                          <Tooltip
                            contentStyle={{ backgroundColor: "#1e293b", border: "1px solid #334155", borderRadius: "8px" }}
                            labelStyle={{ color: "#94a3b8" }}
                            content={({ active, payload, label }) => {
                              if (active && payload && payload.length) {
                                const replayVal = payload.find((p: any) => p.dataKey === 'replay_equity')?.value as number | undefined;
                                const backtestVal = payload.find((p: any) => p.dataKey === 'backtest_equity')?.value as number | undefined;
                                const diff = replayVal != null && backtestVal != null ? replayVal - backtestVal : null;
                                return (
                                  <div className="bg-slate-800 border border-slate-700 rounded-lg p-3 text-xs">
                                    <p className="text-slate-400 mb-2">{label}</p>
                                    <p className="text-blue-400">回放: {replayVal != null ? `$${replayVal.toFixed(2)}` : 'N/A'}</p>
                                    <p className="text-green-400">回测: {backtestVal != null ? `$${backtestVal.toFixed(2)}` : 'N/A'}</p>
                                    {diff != null && (
                                      <p className={`font-bold mt-1 ${diff >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                        差异: {diff >= 0 ? '+' : ''}{diff.toFixed(2)}
                                      </p>
                                    )}
                                  </div>
                                );
                              }
                              return null;
                            }}
                          />
                          <Legend />
                          {/* 差异区域填充 */}
                          <Area 
                            type="monotone" 
                            dataKey="diff" 
                            name="差异" 
                            stroke="none" 
                            fill="url(#diffGradientPos)" 
                            fillOpacity={0.5}
                          />
                          <Line 
                            type="monotone" 
                            dataKey="replay_equity" 
                            name="历史回放" 
                            stroke="#3b82f6" 
                            strokeWidth={2} 
                            dot={false} 
                            connectNulls
                          />
                          <Line 
                            type="monotone" 
                            dataKey="backtest_equity" 
                            name="理想回测" 
                            stroke="#10b981" 
                            strokeWidth={2} 
                            strokeDasharray="5 5"
                            dot={false}
                            connectNulls
                          />
                        </AreaChart>
                      </ResponsiveContainer>
                    </div>
                  )}

                  {/* Data Source Badges + Match Info */}
                  <div className="flex items-center gap-3 mb-4">
                    <DataSourceBadge source={(rbComparison.replay_session?.data_source || "REPLAY") as any} />
                    <span className="text-xs text-slate-400">vs</span>
                    <DataSourceBadge source={(rbComparison.backtest_results?.[0]?.data_source || rbComparison.backtest_record?.data_source || "BACKTEST") as any} />
                    {rbComparison.match_type && (
                      <Badge variant="outline" className={`text-[10px] ${
                        rbComparison.match_type === "no_match" 
                          ? "bg-yellow-500/10 text-yellow-400 border-yellow-500/20"
                          : rbComparison.match_type === "explicit_id"
                          ? "bg-green-500/10 text-green-400 border-green-500/20"
                          : "bg-blue-500/10 text-blue-400 border-blue-500/20"
                      }`}>
                        {rbComparison.match_type === "explicit_id" 
                          ? "精确匹配" 
                          : rbComparison.match_type === "strategy_symbol" 
                          ? "策略+品种匹配" 
                          : rbComparison.match_type === "no_match"
                          ? "未匹配"
                          : "参数哈希匹配"}
                      </Badge>
                    )}
                    {rbComparison.time_overlap_pct != null && (
                      <span className={`text-xs ${(rbComparison.time_overlap_pct || 0) >= 80 ? "text-green-400" : "text-yellow-400"}`}>
                        时间重叠: {rbComparison.time_overlap_pct.toFixed(0)}%
                      </span>
                    )}
                  </div>

                  {/* 无匹配回测记录提示 */}
                  {(rbComparison.match_type === "no_match" || (!rbComparison.backtest_record && !rbComparison.backtest_results?.length)) && (
                    <div className="bg-yellow-500/10 border border-yellow-500/20 rounded-lg p-4 mb-4">
                      <div className="flex items-start gap-3">
                        <AlertTriangle className="w-5 h-5 text-yellow-400 mt-0.5 flex-shrink-0" />
                        <div>
                          <p className="text-sm font-medium text-yellow-400">未找到匹配的回测记录</p>
                          <p className="text-xs text-yellow-300/70 mt-1">
                            {rbComparison.message || "请先在回放页面执行「快速对比回测」以生成匹配的回测数据进行对比分析"}
                          </p>
                          <Link href={`/replay?session_id=${rbComparison.replay_session?.replay_session_id}`}>
                            <Button 
                              variant="outline" 
                              size="sm" 
                              className="mt-3 h-7 text-xs border-yellow-500/30 text-yellow-400 hover:bg-yellow-500/10"
                            >
                              前往回放页面执行回测
                            </Button>
                          </Link>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Metrics Comparison Table (10+ rows from new API) */}
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs text-left">
                      <thead>
                        <tr className="text-slate-500 border-b border-slate-800">
                          <th className="pb-2 font-medium">指标</th>
                          <th className="pb-2 font-medium text-indigo-400 text-right">回放值</th>
                          <th className="pb-2 font-medium text-emerald-400 text-right">回测值</th>
                          <th className="pb-2 font-medium text-center">差异 (Δ)</th>
                          <th className="pb-2 font-medium text-center">说明</th>
                        </tr>
                      </thead>
                      <tbody className="text-slate-300">
                        {(rbComparison.comparisons || []).map((row: { metric: string; label: string; replay_value: number | null; backtest_value: number | null; delta: number | null; interpretation: string }) => {
                          // 负向指标列表 - 这些指标越小越好
                          const negativeMetrics = ['max_drawdown', 'max_drawdown_pct', 'volatility', 'var_95', 'max_consecutive_losses', 'losing_trades'];
                          const isNegativeMetric = negativeMetrics.some(m => row.metric.toLowerCase().includes(m.toLowerCase()));
                          
                          // 检查是否为"数据不可比"
                          const isNotComparable = row.interpretation === '数据不可比';
                          
                          // 智能颜色标记逻辑
                          let deltaColor = "text-slate-400";
                          if (row.delta != null && !isNotComparable) {
                            if (isNegativeMetric) {
                              // 负向指标：delta <= 0 是好的（回放比回测小或相等）
                              deltaColor = row.delta <= 0 ? "text-green-400" : "text-red-400";
                            } else {
                              // 正向指标：delta >= 0 是好的（回放比回测大或相等）
                              deltaColor = row.delta >= 0 ? "text-green-400" : "text-red-400";
                            }
                          }
                          return (
                            <tr key={row.metric} className="border-b border-slate-800/50 hover:bg-slate-800/20">
                              <td className="py-2 pl-0 font-medium">{row.label}</td>
                              <td className="py-2 text-indigo-400 font-mono text-right">
                                {row.replay_value != null 
                                  ? (typeof row.replay_value === 'number' ? `${row.replay_value >= 0 ? "+" : ""}${row.replay_value.toFixed(2)}` : String(row.replay_value))
                                  : "—"}
                              </td>
                              <td className="py-2 text-emerald-400 font-mono text-right">
                                {row.backtest_value != null 
                                  ? (typeof row.backtest_value === 'number' ? `${row.backtest_value >= 0 ? "+" : ""}${row.backtest_value.toFixed(2)}` : String(row.backtest_value))
                                  : "—"}
                              </td>
                              <td className={`py-2 text-center font-mono font-bold ${deltaColor}`}>
                                {row.delta != null && !isNotComparable 
                                  ? `${row.delta > 0 ? '+' : ''}${row.delta.toFixed(2)}` 
                                  : "—"}
                              </td>
                              <td className={`py-2 text-[10px] text-center ${isNotComparable ? 'text-yellow-400/70' : 'text-slate-500'}`}>{row.interpretation}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>

                  {/* Summary Cards */}
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4">
                    <div className="p-3 bg-slate-800/30 rounded-lg border border-slate-700/30">
                      <p className="text-[10px] text-slate-500 uppercase">最终权益</p>
                      <p className={`text-lg font-bold ${(rbComparison.replay_metrics?.final_equity || 0) >= (rbComparison.replay_session?.initial_capital || 0) ? "text-green-400" : "text-red-400"}`}>
                        ${rbComparison.replay_metrics?.final_equity?.toFixed(2) || "—"}
                      </p>
                    </div>
                    <div className="p-3 bg-slate-800/30 rounded-lg border border-slate-700/30">
                      <p className="text-[10px] text-slate-500 uppercase">盈利交易</p>
                      <p className="text-lg font-bold text-green-400">{rbComparison.replay_metrics?.winning_trades || 0}</p>
                    </div>
                    <div className="p-3 bg-slate-800/30 rounded-lg border border-slate-700/30">
                      <p className="text-[10px] text-slate-500 uppercase">亏损交易</p>
                      <p className="text-lg font-bold text-red-400">{rbComparison.replay_metrics?.losing_trades || 0}</p>
                    </div>
                    <div className="p-3 bg-slate-800/30 rounded-lg border border-slate-700/30">
                      <p className="text-[10px] text-slate-500 uppercase">时间重叠</p>
                      <p className={`text-lg font-bold ${(rbComparison.time_overlap_pct || 0) >= 80 ? "text-green-400" : (rbComparison.time_overlap_pct || 0) >= 50 ? "text-yellow-400" : "text-red-400"}`}>
                        {rbComparison.time_overlap_pct?.toFixed(0) || "—"}%
                      </p>
                    </div>
                  </div>

                  {/* 逐笔交易对比 - 可折叠 */}
                  {rbComparison.trade_level_comparison && rbComparison.trade_level_comparison.length > 0 && (
                    <div className="mt-4 border border-slate-700/30 rounded-lg overflow-hidden">
                      <button
                        onClick={() => setTradeLevelExpanded(!tradeLevelExpanded)}
                        className="w-full flex items-center justify-between p-3 bg-slate-800/30 hover:bg-slate-800/50 transition-colors"
                      >
                        <span className="text-sm font-medium text-slate-300 flex items-center gap-2">
                          <Activity className="w-4 h-4 text-orange-400" />
                          逐笔交易对比 ({rbComparison.trade_level_comparison.length} 笔)
                        </span>
                        {tradeLevelExpanded ? (
                          <ChevronDown className="w-4 h-4 text-slate-400" />
                        ) : (
                          <ChevronRight className="w-4 h-4 text-slate-400" />
                        )}
                      </button>
                      
                      {tradeLevelExpanded && (
                        <div className="p-4 overflow-x-auto">
                          <table className="w-full text-xs text-left">
                            <thead>
                              <tr className="text-slate-500 border-b border-slate-800">
                                <th className="pb-2 font-medium whitespace-nowrap">时间</th>
                                <th className="pb-2 font-medium text-indigo-400 text-center" colSpan={2}>回放成交</th>
                                <th className="pb-2 font-medium text-emerald-400 text-center" colSpan={2}>回测成交</th>
                                <th className="pb-2 font-medium text-center">价格差异</th>
                                <th className="pb-2 font-medium text-center">数量差异</th>
                                <th className="pb-2 font-medium text-center">时间差</th>
                              </tr>
                              <tr className="text-slate-600 border-b border-slate-800/50">
                                <th></th>
                                <th className="pb-2 text-center text-indigo-300">价格</th>
                                <th className="pb-2 text-center text-indigo-300">数量</th>
                                <th className="pb-2 text-center text-emerald-300">价格</th>
                                <th className="pb-2 text-center text-emerald-300">数量</th>
                                <th></th>
                                <th></th>
                                <th></th>
                              </tr>
                            </thead>
                            <tbody className="text-slate-300">
                              {rbComparison.trade_level_comparison.slice(0, 30).map((trade: any, idx: number) => (
                                <tr key={idx} className="border-b border-slate-800/50 hover:bg-slate-800/20">
                                  <td className="py-2 text-slate-400 whitespace-nowrap">
                                    {trade.replay_trade?.timestamp 
                                      ? safeFormatDate(trade.replay_trade.timestamp) 
                                      : trade.backtest_trade?.timestamp 
                                        ? safeFormatDate(trade.backtest_trade.timestamp) 
                                        : '-'}
                                  </td>
                                  <td className="py-2 text-center font-mono text-indigo-400">
                                    {trade.replay_trade?.price != null ? `$${trade.replay_trade.price.toFixed(2)}` : '-'}
                                  </td>
                                  <td className="py-2 text-center font-mono text-indigo-400">
                                    {trade.replay_trade?.quantity != null ? trade.replay_trade.quantity.toFixed(4) : '-'}
                                  </td>
                                  <td className="py-2 text-center font-mono text-emerald-400">
                                    {trade.backtest_trade?.price != null ? `$${trade.backtest_trade.price.toFixed(2)}` : '-'}
                                  </td>
                                  <td className="py-2 text-center font-mono text-emerald-400">
                                    {trade.backtest_trade?.quantity != null ? trade.backtest_trade.quantity.toFixed(4) : '-'}
                                  </td>
                                  <td className={`py-2 text-center font-mono font-bold ${
                                    trade.delta_price == null ? 'text-slate-500' :
                                    trade.delta_price >= 0 ? 'text-green-400' : 'text-red-400'
                                  }`}>
                                    {trade.delta_price != null 
                                      ? `${trade.delta_price >= 0 ? '+' : ''}$${trade.delta_price.toFixed(2)}` 
                                      : '-'}
                                  </td>
                                  <td className={`py-2 text-center font-mono ${
                                    trade.delta_quantity == null ? 'text-slate-500' :
                                    Math.abs(trade.delta_quantity) < 0.0001 ? 'text-slate-400' : 'text-yellow-400'
                                  }`}>
                                    {trade.delta_quantity != null 
                                      ? (Math.abs(trade.delta_quantity) < 0.0001 ? '≈' : trade.delta_quantity.toFixed(4))
                                      : '-'}
                                  </td>
                                  <td className={`py-2 text-center font-mono ${
                                    trade.time_diff_seconds == null ? 'text-slate-500' :
                                    Math.abs(trade.time_diff_seconds) < 1 ? 'text-green-400' :
                                    Math.abs(trade.time_diff_seconds) < 60 ? 'text-yellow-400' : 'text-red-400'
                                  }`}>
                                    {trade.time_diff_seconds != null 
                                      ? `${trade.time_diff_seconds.toFixed(1)}秒` 
                                      : '-'}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                          {rbComparison.trade_level_comparison.length > 30 && (
                            <p className="text-xs text-slate-500 text-center mt-2">
                              显示前 30 笔，共 {rbComparison.trade_level_comparison.length} 笔交易
                            </p>
                          )}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Equity curve overlay for comparison tab */}
                  {rbComparison.replay_session && comparisonEquity && comparisonEquity.normalized_replay && comparisonEquity.normalized_replay.length > 0 && (
                    <div className="mt-4">
                      <h4 className="text-sm font-medium mb-2 flex items-center gap-2">
                        <TrendingUp className="w-4 h-4" />
                        权益曲线对比
                      </h4>
                      <ResponsiveContainer width="100%" height={300}>
                        <LineChart data={mergeEquityData(comparisonEquity)}>
                          <CartesianGrid strokeDasharray="3 3" />
                          <XAxis dataKey="index" fontSize={10} />
                          <YAxis fontSize={10} />
                          <Tooltip />
                          <Legend />
                          <Line type="monotone" dataKey="replay" stroke="#f97316" strokeWidth={2} name="回放" dot={false} />
                          <Line type="monotone" dataKey="backtest" stroke="#8b5cf6" strokeWidth={2} name="回测" dot={false} />
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                  )}
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center h-[250px] text-slate-400 gap-4">
                  <div className="w-16 h-16 rounded-full bg-slate-800/50 flex items-center justify-center">
                    <Activity className="w-8 h-8 opacity-40" />
                  </div>
                  <div className="text-center">
                    <p className="text-sm font-medium text-slate-300 mb-1">暂无回放数据</p>
                    <p className="text-xs text-slate-500 max-w-sm">
                      请先在 <Link href="/replay" className="text-cyan-400 hover:underline">历史回放</Link> 页面运行回放后再查看对比分析
                    </p>
                  </div>
                  <Link href="/replay">
                    <Button 
                      variant="outline" 
                      size="sm" 
                      className="h-8 text-xs border-cyan-500/30 text-cyan-400 hover:bg-cyan-500/10"
                    >
                      <Clock className="w-3 h-3 mr-1" /> 前往历史回放
                    </Button>
                  </Link>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </main>
    </div>
  );
}
