"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { History, Loader2, AlertCircle } from "lucide-react";

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
}

interface EliminationHistoryProps {
  className?: string;
}

// ─── Helper Functions ─────────────────────────────────────────────────────────
const formatDate = (dateString: string): string => {
  try {
    const date = new Date(dateString);
    return date.toLocaleString("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return dateString;
  }
};

const formatReason = (reason: string): string => {
  const reasonMap: Record<string, string> = {
    score_below_threshold: "得分低于阈值",
    low_rank: "排名靠后",
    volatility_too_high: "波动率过高",
    return_too_low: "收益率过低",
    efficiency_poor: "效率不足",
  };
  return reasonMap[reason] || reason;
};

// ─── Component ────────────────────────────────────────────────────────────────
export function EliminationHistory({ className }: EliminationHistoryProps) {
  const [records, setRecords] = useState<EliminationRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchHistory = async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(
          "/api/v1/dynamic-selection/history?limit=20"
        );
        if (!res.ok) {
          console.warn(`获取历史记录失败：服务器返回 ${res.status}`);
          setError(`无法加载历史记录：服务器返回 ${res.status}`);
          setRecords([]);
          return;
        }
        const data: EliminationRecord[] = await res.json();
        setRecords(Array.isArray(data) ? data : []);
      } catch (err) {
        console.warn("获取历史记录失败:", err);
        setError("后端服务未连接，无法加载历史记录");
        setRecords([]);
      } finally {
        setLoading(false);
      }
    };

    fetchHistory();
  }, []);

  return (
    <Card className={`bg-slate-900 border-slate-700/50 ${className || ""}`}>
      <CardHeader className="pb-3 border-b border-slate-800/50">
        <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
          <History className="w-4 h-4 text-slate-400" />
          历史淘汰记录
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0">
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
        ) : records.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-slate-500">
            <History className="w-8 h-8 mb-2 opacity-50" />
            <span className="text-sm">暂无淘汰记录</span>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-800/30">
                <tr className="border-b border-slate-700/50">
                  <th className="text-left py-3 px-4 text-slate-400 font-medium text-xs">
                    评估日期
                  </th>
                  <th className="text-center py-3 px-4 text-slate-400 font-medium text-xs">
                    总策略数
                  </th>
                  <th className="text-center py-3 px-4 text-slate-400 font-medium text-xs">
                    淘汰数
                  </th>
                  <th className="text-center py-3 px-4 text-slate-400 font-medium text-xs">
                    存活数
                  </th>
                  <th className="text-left py-3 px-4 text-slate-400 font-medium text-xs">
                    淘汰策略
                  </th>
                  <th className="text-left py-3 px-4 text-slate-400 font-medium text-xs">
                    淘汰原因
                  </th>
                  <th className="text-right py-3 px-4 text-slate-400 font-medium text-xs">
                    预期夏普
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/50">
                {records.map((record) => (
                  <tr
                    key={record.id}
                    className="hover:bg-slate-800/20 transition-colors"
                  >
                    <td className="py-3 px-4">
                      <span className="text-slate-200 font-mono text-xs">
                        {formatDate(record.evaluation_date)}
                      </span>
                    </td>
                    <td className="py-3 px-4 text-center">
                      <span className="text-slate-300 font-mono">
                        {record.total_strategies}
                      </span>
                    </td>
                    <td className="py-3 px-4 text-center">
                      <span className="text-red-400 font-mono font-medium">
                        {record.eliminated_count}
                      </span>
                    </td>
                    <td className="py-3 px-4 text-center">
                      <span className="text-emerald-400 font-mono font-medium">
                        {record.surviving_count}
                      </span>
                    </td>
                    <td className="py-3 px-4">
                      <div className="flex flex-wrap gap-1">
                        {record.eliminated_strategy_ids.length > 0 ? (
                          record.eliminated_strategy_ids.map((strategyId) => (
                            <Badge
                              key={strategyId}
                              variant="outline"
                              className="bg-red-500/10 text-red-400 border-red-500/20 text-xs"
                            >
                              {strategyId}
                            </Badge>
                          ))
                        ) : (
                          <span className="text-slate-500 text-xs">-</span>
                        )}
                      </div>
                    </td>
                    <td className="py-3 px-4">
                      <div className="flex flex-wrap gap-1">
                        {Object.keys(record.elimination_reasons).length > 0 ? (
                          Object.entries(record.elimination_reasons).map(
                            ([strategyId, reason]) => (
                              <span
                                key={strategyId}
                                className="text-xs text-slate-400"
                              >
                                {strategyId}: {formatReason(reason)}
                              </span>
                            )
                          )
                        ) : (
                          <span className="text-slate-500 text-xs">-</span>
                        )}
                      </div>
                    </td>
                    <td className="py-3 px-4 text-right">
                      <span
                        className={`font-mono ${
                          record.expected_sharpe >= 1
                            ? "text-emerald-400"
                            : record.expected_sharpe >= 0
                            ? "text-yellow-400"
                            : "text-red-400"
                        }`}
                      >
                        {record.expected_sharpe?.toFixed(2) ?? "-"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
