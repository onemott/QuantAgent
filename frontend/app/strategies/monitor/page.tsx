"use client";

import { useEffect, useState, useMemo } from "react";
import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  BookOpen, LayoutDashboard, BarChart2, History, Terminal, Activity,
  RefreshCw, PieChart as PieChartIcon, Target, Clock, AlertTriangle, ShieldAlert,
  Play
} from "lucide-react";
import {
  Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  PieChart, Pie, Cell, ResponsiveContainer, Tooltip, Legend
} from "recharts";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { ConfigToolbar } from "@/components/monitor/ConfigToolbar";
import { EliminationAlert } from "@/components/monitor/EliminationAlert";
import { SimulateEliminationDialog } from "@/components/monitor/SimulateEliminationDialog";
import { EliminationHistory } from "@/components/monitor/EliminationHistory";

// ─── Types ────────────────────────────────────────────────────────────────────
interface DimensionScore {
  subject: string;
  score: number;
  fullMark: number;
  return_score?: number;
  risk_score?: number;
  stability_score?: number;
  efficiency_score?: number;
  risk_adjusted_score?: number;
  fill?: string;
}

interface StrategyWeight {
  name: string;
  value: number;
  fill: string;
}

interface StrategyDetail {
  name: string;
  weight: number;
  fill: string;
  score?: number;
  rank?: number;
  status?: "running" | "warning" | "danger";
}

interface MonitorData {
  dimensions: DimensionScore[];
  weights: StrategyWeight[];
  lastUpdated: string;
  activeCount: number;
  totalAllocation: number;
}

// ─── Mock Data ────────────────────────────────────────────────────────────────
const MOCK_DATA: MonitorData = {
  dimensions: [
    { subject: "动量 (Momentum)", score: 85, fullMark: 100 },
    { subject: "均值回归 (Reversion)", score: 65, fullMark: 100 },
    { subject: "波动率 (Volatility)", score: 90, fullMark: 100 },
    { subject: "成交量 (Volume)", score: 70, fullMark: 100 },
    { subject: "市场情绪 (Sentiment)", score: 80, fullMark: 100 },
  ],
  weights: [
    { name: "双均线 (MA)", value: 35, fill: "#3b82f6" },
    { name: "RSI 振荡器", value: 20, fill: "#8b5cf6" },
    { name: "MACD 信号", value: 25, fill: "#10b981" },
    { name: "布林带 (BOLL)", value: 10, fill: "#06b6d4" },
    { name: "ATR 趋势", value: 10, fill: "#f43f5e" },
  ],
  lastUpdated: new Date().toISOString(),
  activeCount: 5,
  totalAllocation: 100000,
};

// ─── Helper Functions ─────────────────────────────────────────────────────────
const getScoreStatus = (score: number): "running" | "warning" | "danger" => {
  if (score >= 60) return "running";
  if (score >= 40) return "warning";
  return "danger";
};

const getStatusBadge = (status: "running" | "warning" | "danger") => {
  switch (status) {
    case "running":
      return (
        <Badge className="bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 hover:bg-emerald-500/20 font-normal">
          运行中
        </Badge>
      );
    case "warning":
      return (
        <Badge className="bg-yellow-500/10 text-yellow-400 border border-yellow-500/20 hover:bg-yellow-500/20 font-normal">
          警告
        </Badge>
      );
    case "danger":
      return (
        <Badge className="bg-red-500/10 text-red-400 border border-red-500/20 hover:bg-red-500/20 font-normal">
          危险
        </Badge>
      );
  }
};

// ─── Main Page ────────────────────────────────────────────────────────────────
export default function StrategyMonitorPage() {
  const [data, setData] = useState<MonitorData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [mounted, setMounted] = useState(false);
  const [evaluateDialogOpen, setEvaluateDialogOpen] = useState(false);
  const [isEvaluating, setIsEvaluating] = useState(false);
  const [simulateTarget, setSimulateTarget] = useState<StrategyDetail | null>(null);
  const [simulateDialogOpen, setSimulateDialogOpen] = useState(false);

  // Calculate strategy details with scores and rankings
  const strategyDetails: StrategyDetail[] = useMemo(() => {
    if (!data) return [];

    // Map dimensions scores to weights by index or name matching
    const details = data.weights.map((weight, index) => {
      // Try to find matching dimension score by index or use a default calculation
      const dimension = data.dimensions[index];
      const score = dimension ? dimension.score : 50;
      const status = getScoreStatus(score);

      return {
        name: weight.name,
        weight: weight.value,
        fill: weight.fill,
        score,
        status,
      };
    });

    // Sort by score descending and assign ranks
    const sorted = [...details].sort((a, b) => (b.score || 0) - (a.score || 0));
    const rankMap = new Map<string, number>();
    sorted.forEach((item, index) => {
      rankMap.set(item.name, index + 1);
    });

    // Return in original order but with ranks assigned
    return details.map(item => ({
      ...item,
      rank: rankMap.get(item.name) || 0,
    }));
  }, [data]);

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      // 使用相对路径请求动态选择数据
      const res = await fetch("/api/v1/dynamic-selection/status");
      if (!res.ok) {
        throw new Error("Failed to fetch monitor data");
      }
      const jsonData = await res.json();
      setData(jsonData);
    } catch (err) {
      console.warn("API request failed, using mock data for preview", err);
      // Fallback to mock data for UI demonstration
      setData(MOCK_DATA);
      setError("后端接口尚未就绪，当前显示模拟数据");
    } finally {
      setLoading(false);
    }
  };

  const handleEvaluate = async () => {
    setIsEvaluating(true);
    setError(null);
    try {
      const res = await fetch("/api/v1/dynamic-selection/evaluate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ force_recalculate: true }),
      });

      if (!res.ok) {
        const errorMsg = `评估触发失败：服务器返回 ${res.status}`;
        console.warn(errorMsg);
        setError(errorMsg);
        return;
      }

      setEvaluateDialogOpen(false);
      fetchData();
    } catch (err) {
      const errorMsg = "后端服务未连接，请检查服务状态";
      console.warn("Failed to trigger evaluation:", err);
      setError(errorMsg);
    } finally {
      setIsEvaluating(false);
    }
  };

  const handleConfirmEliminate = async () => {
    setError(null);
    try {
      const res = await fetch("/api/v1/dynamic-selection/evaluate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ force_recalculate: true }),
      });

      if (!res.ok) {
        const errorMsg = `淘汰确认失败：服务器返回 ${res.status}`;
        console.warn(errorMsg);
        setError(errorMsg);
        return;
      }

      setSimulateDialogOpen(false);
      setSimulateTarget(null);
      fetchData();
    } catch (err) {
      const errorMsg = "后端服务未连接，请检查服务状态";
      console.warn("Failed to confirm elimination:", err);
      setError(errorMsg);
    }
  };

  const handleSimulateClick = (strategy: StrategyDetail) => {
    setSimulateTarget(strategy);
    setSimulateDialogOpen(true);
  };

  useEffect(() => {
    setMounted(true);
    fetchData();
    // 模拟实时更新
    const interval = setInterval(fetchData, 10000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="min-h-screen bg-[#0a0e1a] text-slate-100">
      {/* ── Header ── */}
      <header className="sticky top-0 z-40 border-b border-slate-800/60 bg-[#0a0e1a]/95 backdrop-blur-md">
        <div className="container mx-auto px-4 h-14 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-blue-500/20">
              <Target className="w-4 h-4 text-white" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-slate-100">动态策略监控</h1>
              <p className="text-[10px] text-slate-400">实时维度打分 & 仓位权重分配</p>
            </div>
          </div>

          <nav className="hidden md:flex items-center gap-1">
            <Link href="/dashboard" className="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-100 hover:bg-slate-800 rounded-lg transition-all flex items-center gap-1.5">
              <LayoutDashboard className="w-4 h-4" /> 仪表盘
            </Link>
            <Link href="/backtest" className="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-100 hover:bg-slate-800 rounded-lg transition-all flex items-center gap-1.5">
              <BarChart2 className="w-4 h-4" /> 回测
            </Link>
            <Link href="/strategies" className="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-100 hover:bg-slate-800 rounded-lg transition-all flex items-center gap-1.5">
              <BookOpen className="w-4 h-4" /> 策略库
            </Link>
            <span className="px-3 py-1.5 text-sm text-blue-400 bg-blue-500/10 rounded-lg border border-blue-500/20 font-medium flex items-center gap-1.5">
              <Activity className="w-4 h-4" /> 监控大盘
            </span>
            <Link href="/terminal" className="px-3 py-1.5 text-sm text-slate-400 hover:text-slate-100 hover:bg-slate-800 rounded-lg transition-all flex items-center gap-1.5">
              <Terminal className="w-4 h-4" /> 终端
            </Link>
          </nav>
        </div>
      </header>

      <main className="container mx-auto px-4 py-6 space-y-6">
        {/* ── Config Toolbar ── */}
        <ConfigToolbar
          onRefresh={fetchData}
          onConfigSaved={fetchData}
          loading={loading}
        />

        {/* ── Elimination Alert Banner ── */}
        {data && (
          <EliminationAlert
            dimensions={data.dimensions}
            threshold={40}
            onEvaluate={() => setEvaluateDialogOpen(true)}
          />
        )}

        {/* ── Toolbar & Error Info ── */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <h2 className="text-xl font-bold text-slate-100">实时状态概览</h2>
            {loading && <Badge variant="outline" className="bg-slate-800 text-slate-300 border-slate-700 animate-pulse">更新中...</Badge>}
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs text-slate-400 flex items-center gap-1.5">
              <Clock className="w-3.5 h-3.5" />
              最近更新: {data ? new Date(data.lastUpdated).toLocaleTimeString() : "--"}
            </span>
            <Button
              variant="outline"
              size="sm"
              onClick={fetchData}
              disabled={loading}
              className="border-slate-700 text-slate-300 hover:text-white bg-slate-800/50 h-8"
            >
              <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${loading ? "animate-spin" : ""}`} />
              刷新数据
            </Button>
          </div>
        </div>

        {error && (
          <div className="flex items-center gap-2 text-yellow-400 bg-yellow-500/10 border border-yellow-500/20 rounded-lg px-4 py-3 text-sm">
            <AlertTriangle className="w-4 h-4 flex-shrink-0" /> {error}
          </div>
        )}

        {/* ── Top Stat Cards ── */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Card className="bg-slate-900 border-slate-700/50">
            <CardContent className="p-5 flex items-center gap-4">
              <div className="w-12 h-12 rounded-xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center">
                <ShieldAlert className="w-6 h-6 text-blue-400" />
              </div>
              <div>
                <p className="text-slate-400 text-sm mb-1">活跃策略数</p>
                <p className="text-2xl font-bold text-slate-100 font-mono">{data?.activeCount ?? "-"}</p>
              </div>
            </CardContent>
          </Card>
          <Card className="bg-slate-900 border-slate-700/50">
            <CardContent className="p-5 flex items-center gap-4">
              <div className="w-12 h-12 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center">
                <Target className="w-6 h-6 text-emerald-400" />
              </div>
              <div>
                <p className="text-slate-400 text-sm mb-1">系统总分值 (均分)</p>
                <p className="text-2xl font-bold text-emerald-400 font-mono">
                  {data ? (data.dimensions.reduce((a, b) => a + b.score, 0) / data.dimensions.length).toFixed(1) : "-"}
                </p>
              </div>
            </CardContent>
          </Card>
          <Card className="bg-slate-900 border-slate-700/50">
            <CardContent className="p-5 flex items-center gap-4">
              <div className="w-12 h-12 rounded-xl bg-purple-500/10 border border-purple-500/20 flex items-center justify-center">
                <PieChartIcon className="w-6 h-6 text-purple-400" />
              </div>
              <div>
                <p className="text-slate-400 text-sm mb-1">总分配资金 (USDT)</p>
                <p className="text-2xl font-bold text-slate-100 font-mono">
                  {data?.totalAllocation.toLocaleString() ?? "-"}
                </p>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* ── Charts Row ── */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Radar Chart for Dimension Scores */}
          <Card className="bg-slate-900 border-slate-700/50">
            <CardHeader className="pb-2">
              <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
                <Target className="w-4 h-4 text-blue-400" />
                策略维度评分 (Dimension Scores)
              </CardTitle>
              <CardDescription className="text-xs text-slate-400">
                基于市场状态的多维度实时评估
              </CardDescription>
            </CardHeader>
            <CardContent className="h-[350px] w-full flex items-center justify-center">
              {data && mounted ? (
                <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1}>
                  <RadarChart
                    cx="50%"
                    cy="50%"
                    outerRadius="70%"
                    data={data.dimensions.map(d => ({
                      subject: d.subject,
                      score: d.score,
                      fullMark: d.fullMark,
                      threshold: 40,
                    }))}
                  >
                    <PolarGrid stroke="#334155" />
                    <PolarAngleAxis dataKey="subject" tick={{ fill: "#94a3b8", fontSize: 12 }} />
                    <PolarRadiusAxis angle={30} domain={[0, 100]} tick={{ fill: "#64748b" }} />
                    {/* 当前策略得分 */}
                    <Radar
                      name="当前得分"
                      dataKey="score"
                      stroke="#3b82f6"
                      fill="#3b82f6"
                      fillOpacity={0.4}
                    />
                    {/* 40分淘汰阈值参考线 */}
                    <Radar
                      name="淘汰阈值（40分）"
                      dataKey="threshold"
                      stroke="#ef4444"
                      fill="#ef4444"
                      fillOpacity={0.1}
                      strokeDasharray="5 5"
                      dot={false}
                    />
                    <Legend
                      verticalAlign="bottom"
                      height={36}
                      iconType="plainline"
                      wrapperStyle={{ fontSize: "12px", color: "#cbd5e1" }}
                    />
                    <Tooltip
                      contentStyle={{ backgroundColor: "#1e293b", borderColor: "#334155", borderRadius: "8px" }}
                      itemStyle={{ color: "#3b82f6" }}
                    />
                  </RadarChart>
                </ResponsiveContainer>
              ) : (
                <div className="text-slate-500 flex flex-col items-center">
                  <Activity className="w-8 h-8 mb-2 opacity-50" />
                  <span>暂无评分数据</span>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Pie Chart for Weight Allocation */}
          <Card className="bg-slate-900 border-slate-700/50">
            <CardHeader className="pb-2">
              <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
                <PieChartIcon className="w-4 h-4 text-purple-400" />
                实时权重分配 (Weight Allocation)
              </CardTitle>
              <CardDescription className="text-xs text-slate-400">
                各子策略的动态资金权重分布
              </CardDescription>
            </CardHeader>
            <CardContent className="h-[350px] w-full flex items-center justify-center">
              {data && mounted ? (
                <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1}>
                  <PieChart>
                    <Pie
                      data={data.weights}
                      cx="50%"
                      cy="50%"
                      innerRadius={80}
                      outerRadius={120}
                      paddingAngle={5}
                      dataKey="value"
                      stroke="none"
                    >
                      {data.weights.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={entry.fill} />
                      ))}
                    </Pie>
                    <Tooltip
                      formatter={(value) => [`${value}%`, "权重"]}
                      contentStyle={{ backgroundColor: "#1e293b", borderColor: "#334155", borderRadius: "8px" }}
                    />
                    <Legend
                      verticalAlign="bottom"
                      height={36}
                      iconType="circle"
                      wrapperStyle={{ fontSize: "12px", color: "#cbd5e1" }}
                    />
                  </PieChart>
                </ResponsiveContainer>
              ) : (
                <div className="text-slate-500 flex flex-col items-center">
                  <PieChartIcon className="w-8 h-8 mb-2 opacity-50" />
                  <span>暂无权重数据</span>
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* ── Details Table ── */}
        <Card className="bg-slate-900 border-slate-700/50">
          <CardHeader className="pb-3 border-b border-slate-800/50">
            <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
              <Activity className="w-4 h-4 text-emerald-400" />
              策略状态明细
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-slate-800/30">
                  <tr className="border-b border-slate-700/50">
                    <th className="text-left py-3 px-4 text-slate-400 font-medium">策略名称</th>
                    <th className="text-right py-3 px-4 text-slate-400 font-medium">当前权重</th>
                    <th className="text-right py-3 px-4 text-slate-400 font-medium">目标资金</th>
                    <th className="text-center py-3 px-4 text-slate-400 font-medium">综合得分</th>
                    <th className="text-center py-3 px-4 text-slate-400 font-medium">排名</th>
                    <th className="text-center py-3 px-4 text-slate-400 font-medium">状态</th>
                    <th className="text-center py-3 px-4 text-slate-400 font-medium">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/50">
                  {strategyDetails.map((strategy, idx) => {
                    const isLowScore = (strategy.score || 0) < 40;
                    return (
                      <tr
                        key={idx}
                        className={`hover:bg-slate-800/20 transition-colors ${isLowScore ? "bg-red-500/5" : ""}`}
                      >
                        <td className="py-3 px-4">
                          <div className="flex items-center gap-2">
                            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: strategy.fill }} />
                            <span className="text-slate-200 font-medium">{strategy.name}</span>
                          </div>
                        </td>
                        <td className="py-3 px-4 text-right font-mono text-slate-300">
                          {strategy.weight}%
                        </td>
                        <td className="py-3 px-4 text-right font-mono text-slate-300">
                          {((strategy.weight / 100) * (data?.totalAllocation || 0)).toLocaleString()} USDT
                        </td>
                        <td className="py-3 px-4">
                          <div className="flex items-center gap-2">
                            <span className="text-slate-300 font-mono min-w-[2rem]">{strategy.score ?? "-"}</span>
                            <div className="flex-1 h-1.5 bg-slate-700 rounded-full overflow-hidden max-w-[80px]">
                              <div
                                className="h-full rounded-full transition-all"
                                style={{
                                  width: `${strategy.score || 0}%`,
                                  backgroundColor: strategy.fill,
                                }}
                              />
                            </div>
                          </div>
                        </td>
                        <td className="py-3 px-4 text-center">
                          <span className="text-slate-300 font-mono">
                            {strategy.rank ? `${strategy.rank}/${strategyDetails.length}` : "-"}
                          </span>
                        </td>
                        <td className="py-3 px-4 text-center">
                          {strategy.status ? getStatusBadge(strategy.status) : "-"}
                        </td>
                        <td className="py-3 px-4 text-center">
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => handleSimulateClick(strategy)}
                            className="border-slate-700 text-slate-400 hover:text-slate-200 hover:bg-slate-800 h-7 text-xs"
                          >
                            模拟淘汰
                          </Button>
                        </td>
                      </tr>
                    );
                  })}
                  {strategyDetails.length === 0 && (
                    <tr>
                      <td colSpan={7} className="py-8 text-center text-slate-500">
                        暂无策略明细数据
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>

        {/* ── Elimination History ── */}
        <EliminationHistory />
      </main>

      {/* ── Evaluate Confirmation Dialog ── */}
      <Dialog open={evaluateDialogOpen} onOpenChange={setEvaluateDialogOpen}>
        <DialogContent className="bg-slate-900 border-slate-700">
          <DialogHeader>
            <DialogTitle className="text-slate-100">确认触发评估</DialogTitle>
            <DialogDescription className="text-slate-400">
              这将立即重新计算所有策略的评分和权重分配。是否继续？
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2">
            <Button
              variant="outline"
              onClick={() => setEvaluateDialogOpen(false)}
              className="border-slate-700 text-slate-300"
            >
              取消
            </Button>
            <Button
              onClick={handleEvaluate}
              disabled={isEvaluating}
              className="bg-blue-600 hover:bg-blue-500 text-white"
            >
              {isEvaluating ? "执行中..." : "确认触发"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Simulate Elimination Dialog ── */}
      <SimulateEliminationDialog
        open={simulateDialogOpen}
        onOpenChange={setSimulateDialogOpen}
        strategy={simulateTarget}
        allWeights={data?.weights || []}
        totalAllocation={data?.totalAllocation || 0}
        onConfirmEliminate={handleConfirmEliminate}
      />
    </div>
  );
}
