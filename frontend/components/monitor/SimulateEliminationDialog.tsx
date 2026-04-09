"use client";

import { useMemo } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { AlertTriangle, TrendingUp, Target, PieChart } from "lucide-react";

// ─── Types ────────────────────────────────────────────────────────────────────
// 策略明细类型（来自 page.tsx 的 StrategyDetail）
interface StrategyDetail {
  name: string;
  weight: number;
  fill: string;
  score?: number;
  rank?: number;
  status?: "running" | "warning" | "danger";
}

// 策略权重类型（来自 page.tsx 的 StrategyWeight）
interface StrategyWeight {
  name: string;
  value: number;
  fill: string;
}

interface SimulateEliminationDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  strategy: StrategyDetail | null;
  allWeights: StrategyWeight[];
  totalAllocation: number;
  onConfirmEliminate: () => void;
}

interface WeightRedistribution {
  name: string;
  originalValue: number;
  newValue: number;
  change: number;
  newTargetAllocation: number;
  fill: string;
}

// ─── Helper Functions ─────────────────────────────────────────────────────────
const formatNumber = (num: number, decimals: number = 1): string => {
  return num.toFixed(decimals);
};

const formatCurrency = (num: number): string => {
  return num.toLocaleString("en-US", { maximumFractionDigits: 0 });
};

// ─── Component ────────────────────────────────────────────────────────────────
export function SimulateEliminationDialog({
  open,
  onOpenChange,
  strategy,
  allWeights,
  totalAllocation,
  onConfirmEliminate,
}: SimulateEliminationDialogProps) {
  // Calculate weight redistribution
  const redistribution = useMemo<WeightRedistribution[]>(() => {
    if (!strategy || allWeights.length === 0) return [];

    // Remove target strategy
    const remaining = allWeights.filter((w) => w.name !== strategy.name);
    const totalRemaining = remaining.reduce((sum, w) => sum + w.value, 0);

    if (totalRemaining === 0) return [];

    // Calculate new weights proportionally
    return remaining.map((w) => {
      const newValue = Math.round((w.value / totalRemaining) * 100 * 10) / 10;
      return {
        name: w.name,
        originalValue: w.value,
        newValue,
        change: newValue - w.value,
        newTargetAllocation: Math.round((newValue / 100) * totalAllocation),
        fill: w.fill,
      };
    });
  }, [strategy, allWeights, totalAllocation]);

  // Current strategy info
  const currentTargetAllocation = strategy
    ? Math.round((strategy.weight / 100) * totalAllocation)
    : 0;

  // Summary stats
  const summaryStats = useMemo(() => {
    if (!strategy || redistribution.length === 0)
      return { newCount: 0, totalWeight: 0 };
    return {
      newCount: redistribution.length,
      totalWeight: redistribution.reduce((sum, w) => sum + w.newValue, 0),
    };
  }, [strategy, redistribution]);

  if (!strategy) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-slate-900 border-slate-700 max-w-2xl">
        <DialogHeader>
          <DialogTitle className="text-slate-100 flex items-center gap-2">
            <AlertTriangle className="w-5 h-5 text-red-400" />
            模拟淘汰预览 - {strategy.name}
          </DialogTitle>
          <DialogDescription className="text-slate-400">
            预览淘汰该策略后的权重重分配情况，确认后将触发重新评估
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* Current Status Overview */}
          <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700/50">
            <h4 className="text-sm font-medium text-slate-300 mb-3 flex items-center gap-2">
              <Target className="w-4 h-4 text-blue-400" />
              当前状态概览
            </h4>
            <div className="grid grid-cols-3 gap-4">
              <div>
                <p className="text-xs text-slate-500 mb-1">当前权重</p>
                <p className="text-lg font-mono text-slate-200">
                  {strategy.weight}%
                </p>
              </div>
              <div>
                <p className="text-xs text-slate-500 mb-1">综合得分</p>
                <p
                  className={`text-lg font-mono ${
                    (strategy.score ?? 0) < 40
                      ? "text-red-400"
                      : (strategy.score ?? 0) < 60
                      ? "text-yellow-400"
                      : "text-emerald-400"
                  }`}
                >
                  {strategy.score ?? "-"}
                </p>
              </div>
              <div>
                <p className="text-xs text-slate-500 mb-1">目标资金</p>
                <p className="text-lg font-mono text-slate-200">
                  {formatCurrency(currentTargetAllocation)} USDT
                </p>
              </div>
            </div>
          </div>

          {/* Weight Redistribution Preview Table */}
          <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700/50">
            <h4 className="text-sm font-medium text-slate-300 mb-3 flex items-center gap-2">
              <PieChart className="w-4 h-4 text-purple-400" />
              淘汰后权重重分配预览
            </h4>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-slate-700/30">
                  <tr className="border-b border-slate-700/50">
                    <th className="text-left py-2 px-3 text-slate-400 font-medium text-xs">
                      策略名称
                    </th>
                    <th className="text-right py-2 px-3 text-slate-400 font-medium text-xs">
                      原权重
                    </th>
                    <th className="text-right py-2 px-3 text-slate-400 font-medium text-xs">
                      新权重
                    </th>
                    <th className="text-right py-2 px-3 text-slate-400 font-medium text-xs">
                      权重变化
                    </th>
                    <th className="text-right py-2 px-3 text-slate-400 font-medium text-xs">
                      新目标资金
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-700/30">
                  {redistribution.map((item, idx) => (
                    <tr key={idx} className="hover:bg-slate-700/20">
                      <td className="py-2 px-3">
                        <div className="flex items-center gap-2">
                          <span
                            className="w-2 h-2 rounded-full"
                            style={{ backgroundColor: item.fill }}
                          />
                          <span className="text-slate-200">{item.name}</span>
                        </div>
                      </td>
                      <td className="py-2 px-3 text-right font-mono text-slate-400">
                        {item.originalValue}%
                      </td>
                      <td className="py-2 px-3 text-right font-mono text-slate-200">
                        {formatNumber(item.newValue)}%
                      </td>
                      <td className="py-2 px-3 text-right font-mono">
                        <span
                          className={
                            item.change >= 0 ? "text-emerald-400" : "text-red-400"
                          }
                        >
                          {item.change >= 0 ? "+" : ""}
                          {formatNumber(item.change)}%
                        </span>
                      </td>
                      <td className="py-2 px-3 text-right font-mono text-slate-200">
                        {formatCurrency(item.newTargetAllocation)} USDT
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Expected Changes Summary */}
          <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700/50">
            <h4 className="text-sm font-medium text-slate-300 mb-3 flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-emerald-400" />
              预期组合变化
            </h4>
            <div className="flex flex-wrap gap-3">
              <Badge
                variant="outline"
                className="bg-slate-700/30 border-slate-600 text-slate-300"
              >
                策略数量: {allWeights.length} → {summaryStats.newCount}
              </Badge>
              <Badge
                variant="outline"
                className="bg-slate-700/30 border-slate-600 text-slate-300"
              >
                总权重: {formatNumber(summaryStats.totalWeight)}%
              </Badge>
              <Badge
                variant="outline"
                className="bg-red-500/10 border-red-500/30 text-red-400"
              >
                淘汰策略: {strategy.name}
              </Badge>
            </div>
          </div>
        </div>

        <DialogFooter className="gap-2 mt-4">
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            className="border-slate-700 text-slate-300 hover:text-white"
          >
            取消
          </Button>
          <Button
            onClick={onConfirmEliminate}
            className="bg-red-600 hover:bg-red-500 text-white"
          >
            <AlertTriangle className="w-4 h-4 mr-1.5" />
            确认淘汰
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
