"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  ArrowLeft, RefreshCw, Download, TrendingUp, TrendingDown,
  BarChart3, Clock, DollarSign, Filter, AlertTriangle,
} from "lucide-react";

const API_BASE = ""; // 客户端请求强制使用相对路径，通过 Next.js rewrites 转发到后端

interface TradePair {
  pair_id: string;
  symbol: string;
  side: string;
  status: string;
  entry_price: number | null;
  exit_price: number | null;
  quantity: number | null;
  entry_time: string | null;
  exit_time: string | null;
  pnl: number | null;
  pnl_pct: number | null;
  holding_hours: number | null;
  holding_costs: number;
}

export default function TradesPage() {
  const [pairs, setPairs] = useState<TradePair[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [symbolFilter, setSymbolFilter] = useState<string>("");
  const [page, setPage] = useState(1);
  const [pageSize] = useState(50);
  const [totalCount, setTotalCount] = useState(0);

  const fetchPairs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const offset = (page - 1) * pageSize;
      let url = `${API_BASE}/api/v1/analytics/trade-pairs?limit=${pageSize}&offset=${offset}`;
      if (statusFilter !== "all") url += `&status=${statusFilter}`;
      if (symbolFilter) url += `&symbol=${symbolFilter}`;

      const res = await fetch(url);
      if (res.ok) {
        const data = await res.json();
        setPairs(data.pairs || []);
        setTotalCount(data.total || data.pairs?.length || 0);
      } else {
        setError(`请求失败 (${res.status})，请检查后端服务是否运行`);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "网络错误";
      setError(`无法连接到服务器: ${msg}，请确保后端服务已启动`);
    } finally {
      setLoading(false);
    }
  }, [statusFilter, symbolFilter, page, pageSize]);

  // 重置页码当筛选条件改变时
  useEffect(() => {
    setPage(1);
  }, [statusFilter, symbolFilter]);

  useEffect(() => {
    fetchPairs();
  }, [fetchPairs]);

  const handleExportCSV = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/analytics/export/trades?format=csv&limit=1000`);
      if (res.ok) {
        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `trades_${new Date().toISOString().slice(0, 10)}.csv`;
        a.click();
        window.URL.revokeObjectURL(url);
      }
    } catch (e) {
      console.error("Export failed:", e);
    }
  };

  const formatTime = (t: string | null) =>
    t ? new Date(t).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "-";
  const formatMoney = (v: number | null) =>
    v != null ? `$${v.toFixed(2)}` : "-";
  const formatPct = (v: number | null) =>
    v != null ? `${v >= 0 ? "+" : ""}${v.toFixed(2)}%` : "-";

  // Summary stats
  const closedPairs = pairs.filter(p => p.status === "CLOSED");
  const openPairs = pairs.filter(p => p.status === "OPEN");
  const totalPnl = closedPairs.reduce((s, p) => s + (p.pnl || 0), 0);
  const winCount = closedPairs.filter(p => p.pnl && p.pnl > 0).length;
  const winRate = closedPairs.length > 0 ? (winCount / closedPairs.length * 100) : 0;
  const avgHolding = closedPairs.length > 0
    ? closedPairs.reduce((s, p) => s + (p.holding_hours || 0), 0) / closedPairs.length
    : 0;

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
              <div className="w-9 h-9 bg-gradient-to-br from-blue-500 to-purple-600 rounded-xl flex items-center justify-center">
                <BarChart3 className="w-5 h-5 text-white" />
              </div>
              <div>
                <h1 className="text-lg font-bold text-slate-100">交易流水</h1>
                <p className="text-[10px] text-slate-400">Trade Pairs & History</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button variant="ghost" size="sm" className="h-8 text-xs text-slate-400 hover:text-slate-100" onClick={fetchPairs}>
                <RefreshCw className="w-3 h-3 mr-1" /> 刷新
              </Button>
              <Button variant="outline" size="sm" className="h-8 text-xs border-slate-700 text-slate-300 hover:bg-slate-800" onClick={handleExportCSV}>
                <Download className="w-3 h-3 mr-1" /> 导出CSV
              </Button>
              <Link href="/analytics">
                <Button variant="outline" size="sm" className="h-8 text-xs border-blue-500/30 text-blue-400 hover:bg-blue-500/10">
                  性能分析
                </Button>
              </Link>
            </div>
          </div>
        </div>
      </header>

      <main className="container mx-auto px-4 py-6 space-y-6">
        {/* Summary Cards */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <Card className="bg-gradient-to-br from-slate-900 to-slate-800/50 border-slate-700/50">
            <CardContent className="p-4">
              <p className="text-xs text-slate-400">总交易数</p>
              <p className="text-2xl font-bold text-slate-100">{pairs.length}</p>
              <p className="text-xs text-slate-500 mt-1">
                {openPairs.length} 持仓 / {closedPairs.length} 已平仓
              </p>
            </CardContent>
          </Card>

          <Card className="bg-gradient-to-br from-slate-900 to-slate-800/50 border-slate-700/50">
            <CardContent className="p-4">
              <p className="text-xs text-slate-400">总盈亏</p>
              <p className={`text-2xl font-bold ${totalPnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                {totalPnl >= 0 ? "+" : ""}{formatMoney(totalPnl)}
              </p>
            </CardContent>
          </Card>

          <Card className="bg-gradient-to-br from-slate-900 to-slate-800/50 border-slate-700/50">
            <CardContent className="p-4">
              <p className="text-xs text-slate-400">胜率</p>
              <p className="text-2xl font-bold text-purple-400">{winRate.toFixed(1)}%</p>
              <p className="text-xs text-slate-500 mt-1">{winCount} / {closedPairs.length}</p>
            </CardContent>
          </Card>

          <Card className="bg-gradient-to-br from-slate-900 to-slate-800/50 border-slate-700/50">
            <CardContent className="p-4">
              <p className="text-xs text-slate-400">平均持仓</p>
              <p className="text-2xl font-bold text-blue-400">{avgHolding.toFixed(1)}h</p>
            </CardContent>
          </Card>

          <Card className="bg-gradient-to-br from-slate-900 to-slate-800/50 border-slate-700/50">
            <CardContent className="p-4">
              <p className="text-xs text-slate-400">总费用</p>
              <p className="text-2xl font-bold text-yellow-400">
                ${closedPairs.reduce((s, p) => s + (p.holding_costs || 0), 0).toFixed(2)}
              </p>
            </CardContent>
          </Card>
        </div>

        {/* Filters */}
        <div className="flex items-center gap-3">
          <Filter className="w-4 h-4 text-slate-500" />
          <Tabs value={statusFilter} onValueChange={setStatusFilter}>
            <TabsList>
              <TabsTrigger value="all">全部</TabsTrigger>
              <TabsTrigger value="OPEN">持仓中</TabsTrigger>
              <TabsTrigger value="CLOSED">已平仓</TabsTrigger>
            </TabsList>
          </Tabs>
          <input
            type="text"
            placeholder="筛选交易对..."
            value={symbolFilter}
            onChange={e => setSymbolFilter(e.target.value.toUpperCase())}
            className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus:border-blue-500 w-40"
          />
        </div>

        {/* Trade Pairs Table */}
        <Card className="bg-gradient-to-br from-slate-900 to-slate-800/30 border-slate-700/50">
          <CardHeader className="pb-3">
            <CardTitle className="text-slate-100 text-base">
              交易对列表
              <Badge variant="outline" className="ml-2 text-[10px] bg-blue-500/10 text-blue-400 border-blue-500/20">
                {pairs.length}
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            {error ? (
              <div className="flex flex-col items-center justify-center py-16 text-red-400">
                <AlertTriangle className="w-12 h-12 mb-3 opacity-50" />
                <p className="font-medium">连接失败</p>
                <p className="text-xs text-slate-500 mt-1">{error}</p>
              </div>
            ) : loading ? (
              <div className="flex items-center justify-center py-12 text-slate-500">
                <RefreshCw className="w-5 h-5 animate-spin mr-2" /> 加载中...
              </div>
            ) : pairs.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-16 text-slate-500">
                <BarChart3 className="w-12 h-12 mb-3 opacity-30" />
                <p>暂无交易记录</p>
                <p className="text-xs text-slate-600 mt-1">完成交易后，配对记录将自动显示</p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>配对ID</TableHead>
                      <TableHead>交易对</TableHead>
                      <TableHead>方向</TableHead>
                      <TableHead>数量</TableHead>
                      <TableHead>入场价</TableHead>
                      <TableHead>出场价</TableHead>
                      <TableHead>入场时间</TableHead>
                      <TableHead>出场时间</TableHead>
                      <TableHead>持仓时长</TableHead>
                      <TableHead>盈亏</TableHead>
                      <TableHead>状态</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {pairs.map(pair => (
                      <TableRow key={pair.pair_id}>
                        <TableCell className="font-mono text-xs text-slate-400">
                          {pair.pair_id.slice(0, 8)}...
                        </TableCell>
                        <TableCell className="font-medium">{pair.symbol}</TableCell>
                        <TableCell>
                          <Badge
                            variant={pair.side === "LONG" ? "default" : "destructive"}
                            className={pair.side === "LONG"
                              ? "bg-green-500/15 text-green-400 border-green-500/20"
                              : "bg-red-500/15 text-red-400 border-red-500/20"
                            }
                          >
                            {pair.side === "LONG" ? (
                              <><TrendingUp className="w-3 h-3 mr-1" /> LONG</>
                            ) : (
                              <><TrendingDown className="w-3 h-3 mr-1" /> SHORT</>
                            )}
                          </Badge>
                        </TableCell>
                        <TableCell className="font-mono text-sm">{pair.quantity?.toFixed(4)}</TableCell>
                        <TableCell className="font-mono text-sm">{formatMoney(pair.entry_price)}</TableCell>
                        <TableCell className="font-mono text-sm">
                          {pair.exit_price ? formatMoney(pair.exit_price) : "-"}
                        </TableCell>
                        <TableCell className="text-xs text-slate-400">{formatTime(pair.entry_time)}</TableCell>
                        <TableCell className="text-xs text-slate-400">
                          {pair.exit_time ? formatTime(pair.exit_time) : "-"}
                        </TableCell>
                        <TableCell>
                          {pair.holding_hours != null ? (
                            <span className="flex items-center gap-1 text-xs text-slate-300">
                              <Clock className="w-3 h-3 text-slate-500" />
                              {pair.holding_hours.toFixed(1)}h
                            </span>
                          ) : "-"}
                        </TableCell>
                        <TableCell>
                          {pair.pnl != null ? (
                            <div>
                              <span className={`font-bold text-sm ${pair.pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                                {pair.pnl >= 0 ? "+" : ""}{formatMoney(pair.pnl)}
                              </span>
                              <span className={`block text-[10px] ${(pair.pnl_pct || 0) >= 0 ? "text-green-400/70" : "text-red-400/70"}`}>
                                {formatPct(pair.pnl_pct)}
                              </span>
                            </div>
                          ) : "-"}
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant="outline"
                            className={pair.status === "OPEN"
                              ? "bg-blue-500/10 text-blue-400 border-blue-500/20"
                              : "bg-slate-500/10 text-slate-400 border-slate-500/20"
                            }
                          >
                            {pair.status === "OPEN" ? "持仓中" : "已平仓"}
                          </Badge>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>

                {/* Pagination */}
                {pairs.length > 0 && (
                  <div className="flex items-center justify-between mt-4 px-2">
                    <div className="text-xs text-slate-400">
                      显示 {(page - 1) * pageSize + 1} - {Math.min(page * pageSize, totalCount)} 条，共 {totalCount} 条
                    </div>
                    <div className="flex items-center gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-7 text-xs"
                        disabled={page === 1}
                        onClick={() => setPage(p => Math.max(1, p - 1))}
                      >
                        上一页
                      </Button>
                      <span className="text-xs text-slate-400 px-2">
                        第 {page} / {Math.max(1, Math.ceil(totalCount / pageSize))} 页
                      </span>
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-7 text-xs"
                        disabled={pairs.length < pageSize || page >= Math.ceil(totalCount / pageSize)}
                        onClick={() => setPage(p => p + 1)}
                      >
                        下一页
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </main>
    </div>
  );
}
