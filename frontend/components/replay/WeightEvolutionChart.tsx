"use client";

import { useEffect, useState, useMemo } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Loader2, AlertCircle, TrendingUp } from "lucide-react";

// ─── Types ────────────────────────────────────────────────────────────────────
interface EliminationRecord {
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
  // 休眠与复活相关字段
  hibernating_strategy_ids?: string[];
  revived_strategy_ids?: string[];
  revival_reasons?: Record<string, string>;
}

interface WeightEvolutionChartProps {
  sessionId: string;
  className?: string;
  isRunning?: boolean;
  data?: EliminationRecord[];  // Optional: external data (used for shared polling)
}

// ─── Color Palette for Strategy Lines ────────────────────────────────────────
const STRATEGY_COLORS = [
  "#6366f1", // Indigo
  "#22c55e", // Green
  "#f59e0b", // Amber
  "#ef4444", // Red
  "#8b5cf6", // Purple
  "#06b6d4", // Cyan
  "#ec4899", // Pink
  "#84cc16", // Lime
  "#f97316", // Orange
  "#14b8a6", // Teal
];

// ─── Helper: Format date for X-axis ───────────────────────────────────────────
const formatXAxisDate = (dateString: string): string => {
  try {
    const date = new Date(dateString);
    return date.toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return dateString;
  }
};

// ─── Component ────────────────────────────────────────────────────────────────
export function WeightEvolutionChart({
  sessionId,
  className,
  isRunning,
  data: externalData,
}: WeightEvolutionChartProps) {
  const [records, setRecords] = useState<EliminationRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastFetchStatus, setLastFetchStatus] = useState<string>('idle');

  // Use external data if provided, otherwise use internal polling
  useEffect(() => {
    if (externalData !== undefined) {
      // External data provided - use it directly
      console.log('[WeightEvolutionChart] Using external data:', {
        recordCount: externalData.length,
        sessionId,
      });
      // Sort by evaluation_date ascending for proper timeline display
      const sorted = [...externalData].sort(
        (a, b) =>
          new Date(a.evaluation_date).getTime() -
          new Date(b.evaluation_date).getTime()
      );
      setRecords(sorted);
      setLoading(false);
      setError(null);
      setLastFetchStatus(externalData.length > 0 ? 'success' : 'empty_data');
      return;
    }

    // No external data - use internal polling logic
    const abortController = new AbortController();

    const fetchHistory = async (isPolling = false) => {
      if (!sessionId) {
        console.log('[WeightEvolutionChart] No sessionId, skipping fetch');
        setLoading(false);
        setLastFetchStatus('no_session');
        return;
      }

      if (!isPolling) setLoading(true);
      setError(null);
      setLastFetchStatus('fetching');
      try {
        const res = await fetch(
          `/api/v1/dynamic-selection/history?session_id=${sessionId}&limit=100`,
          { signal: abortController.signal }
        );
        if (!res.ok) {
          console.warn(`获取权重历史失败：服务器返回 ${res.status}`);
          if (!isPolling) setError(`无法加载权重历史：服务器返回 ${res.status}`);
          setRecords([]);
          setLastFetchStatus(`error_${res.status}`);
          return;
        }
        const data: EliminationRecord[] = await res.json();
        // Sort by evaluation_date ascending for proper timeline display
        const sorted = Array.isArray(data)
          ? [...data].sort(
              (a, b) =>
                new Date(a.evaluation_date).getTime() -
                new Date(b.evaluation_date).getTime()
            )
          : [];
        setRecords(sorted);
        setLastFetchStatus(sorted.length > 0 ? 'success' : 'empty_data');
        console.log('[WeightEvolutionChart] Fetched records:', sorted.length);
      } catch (err: any) {
        // Ignore abort errors
        if (err.name === 'AbortError') return;
        console.warn("获取权重历史失败:", err);
        if (!isPolling) setError("后端服务未连接，无法加载权重历史");
        setRecords([]);
        setLastFetchStatus('error_network');
      } finally {
        setLoading(false);
      }
    };

    fetchHistory();

    let intervalId: NodeJS.Timeout | null = null;
    if (isRunning) {
      intervalId = setInterval(() => fetchHistory(true), 5000);
    }

    return () => {
      abortController.abort();
      if (intervalId) clearInterval(intervalId);
    };
  }, [sessionId, isRunning, externalData]);

  // Extract all unique strategy IDs from the records
  const strategyIds = useMemo(() => {
    const ids = new Set<string>();
    records.forEach((record) => {
      Object.keys(record.strategy_weights ?? {}).forEach((id) => ids.add(id));
    });
    return Array.from(ids);
  }, [records]);

  // Compute hibernating status per strategy per time point
  // Returns: Map<strategyId, Set<timeIndex>> - the time indices where the strategy is hibernating
  const hibernatingStatus = useMemo(() => {
    const status = new Map<string, Set<number>>();
    strategyIds.forEach(id => status.set(id, new Set()));
    
    records.forEach((record, index) => {
      const hibernatingIds = record.hibernating_strategy_ids ?? [];
      hibernatingIds.forEach(id => {
        if (status.has(id)) {
          status.get(id)!.add(index);
        }
      });
    });
    return status;
  }, [records, strategyIds]);

  // Compute revival events: Map<strategyId, Array<{index: number, reason: string}>>
  const revivalEvents = useMemo(() => {
    const events = new Map<string, Array<{index: number; reason: string}>>();
    
    records.forEach((record, index) => {
      const revivedIds = record.revived_strategy_ids ?? [];
      const reasons = record.revival_reasons ?? {};
      revivedIds.forEach(id => {
        if (!events.has(id)) {
          events.set(id, []);
        }
        events.get(id)!.push({
          index,
          reason: reasons[id] || '复活'
        });
      });
    });
    return events;
  }, [records]);

  // Transform data for Recharts: each record becomes a data point
  // with weights for each strategy
  const chartData = useMemo(() => {
    return records.map((record, index) => {
      const point: Record<string, number | string | Record<string, string>[]> = {
        time: formatXAxisDate(record.evaluation_date),
        evaluationIndex: index + 1,
        // Store revival events for this time point
        _revivals: (record.revived_strategy_ids ?? []).map(id => ({
          strategyId: id,
          reason: record.revival_reasons?.[id] || ''
        }))
      };
      // Add weight for each strategy with clamp validation
      Object.entries(record.strategy_weights ?? {}).forEach(
        ([strategyId, rawWeight]) => {
          const weight = typeof rawWeight === 'number' 
            ? Math.max(0, Math.min(1, rawWeight)) 
            : 0;
          if (rawWeight !== weight) {
            console.warn(`权重数据异常: strategy=${strategyId}, raw=${rawWeight}, clamped=${weight}`);
          }
          point[strategyId] = weight;
        }
      );
      return point;
    });
  }, [records]);

  // Check if there's any data to display
  const hasData = chartData.length > 0 && strategyIds.length > 0;

  return (
    <Card
      className={`bg-slate-900 border-slate-700/50 ${className || ""}`}
    >
      <CardHeader className="pb-3 border-b border-slate-800/50">
        <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
          <TrendingUp className="w-4 h-4 text-slate-400" />
          策略权重变化
          {records.length > 0 && (
            <span className="text-xs font-normal text-slate-400 ml-1">
              ({records.length} 轮评估)
            </span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="p-4">
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="w-6 h-6 text-slate-500 animate-spin mr-2" />
            <span className="text-slate-500 text-sm">加载中...</span>
          </div>
        ) : error ? (
          <div className="flex items-center justify-center py-12 text-red-400">
            <AlertCircle className="w-5 h-5 mr-2" />
            <span className="text-sm">{error}</span>
          </div>
        ) : !hasData ? (
          <div className="flex flex-col items-center justify-center py-12 text-slate-500">
            <TrendingUp className="w-8 h-8 mb-2 opacity-50" />
            <span className="text-sm">
              {isRunning ? '等待评估数据...' : '暂无权重变化数据'}
            </span>
            <div className="text-xs text-slate-600 mt-2 space-y-1">
              <div>Session ID: {sessionId || '未获取'}</div>
              <div>请求状态: {lastFetchStatus}</div>
              <div>数据条数: {records.length}</div>
              {isRunning && (
                <div className="text-emerald-400 mt-2">
                  策略运行中，等待第一个评估周期完成...
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="w-full" style={{ height: "280px" }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={chartData}
                margin={{ top: 10, right: 30, left: 0, bottom: 0 }}
              >
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="#1e293b"
                  vertical={false}
                />
                <XAxis
                  dataKey="time"
                  tick={{ fill: "#94a3b8", fontSize: 10 }}
                  axisLine={{ stroke: "#334155" }}
                  tickLine={{ stroke: "#334155" }}
                  angle={-45}
                  textAnchor="end"
                  height={60}
                  interval="preserveStartEnd"
                />
                <YAxis
                  domain={[0, 1]}
                  tick={{ fill: "#94a3b8", fontSize: 10 }}
                  axisLine={{ stroke: "#334155" }}
                  tickLine={{ stroke: "#334155" }}
                  tickFormatter={(v) => `${(v * 100).toFixed(0)}%`}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#0f172a",
                    border: "1px solid #334155",
                    borderRadius: "8px",
                    fontSize: "12px",
                  }}
                  labelStyle={{ color: "#94a3b8" }}
                  formatter={(value) =>
                    typeof value === "number" ? `${(value * 100).toFixed(1)}%` : value
                  }
                />
                <Legend
                  wrapperStyle={{
                    fontSize: "10px",
                    color: "#94a3b8",
                  }}
                  iconType="line"
                  iconSize={10}
                />
                {strategyIds.map((strategyId, index) => {
                  const hibernatingIndices = hibernatingStatus.get(strategyId) || new Set<number>();
                  const isHibernating = hibernatingIndices.size > 0;
                  const color = STRATEGY_COLORS[index % STRATEGY_COLORS.length];
                  
                  return (
                    <Line
                      key={strategyId}
                      type="monotone"
                      dataKey={strategyId}
                      stroke={color}
                      strokeWidth={2}
                      strokeDasharray={isHibernating ? "5 5" : undefined}
                      strokeOpacity={isHibernating ? 0.4 : 1}
                      dot={false}
                      activeDot={{ r: 4 }}
                      connectNulls
                    />
                  );
                })}
                {/* Revival events marker */}
                {strategyIds.map((strategyId, index) => {
                  const events = revivalEvents.get(strategyId) || [];
                  if (events.length === 0) return null;
                  
                  const revivalData = events.map(e => ({
                    time: chartData[e.index]?.time,
                    [strategyId]: chartData[e.index]?.[strategyId],
                    reason: e.reason
                  }));
                  
                  return (
                    <Scatter
                      key={`revival-${strategyId}`}
                      data={revivalData}
                      dataKey={strategyId}
                      fill="#22c55e"
                      shape="circle"
                      r={6}
                    />
                  );
                })}              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default WeightEvolutionChart;
