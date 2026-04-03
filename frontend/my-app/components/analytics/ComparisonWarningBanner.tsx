"use client";

import { AlertTriangle } from "lucide-react";
import { DataSourceBadge } from "./DataSourceBadge";

interface ComparisonWarningBannerProps {
  replayDataSource?: string;
  backtestDataSource?: string;
  paramDiffs: Record<string, { replay: unknown; backtest: unknown }>;
  timeOverlapPct: number;
  symbol?: string;
  strategyType?: string;
}

export function ComparisonWarningBanner({
  replayDataSource = "REPLAY",
  backtestDataSource = "BACKTEST",
  paramDiffs,
  timeOverlapPct,
  symbol,
  strategyType,
}: ComparisonWarningBannerProps) {
  const hasParamDiffs = Object.keys(paramDiffs).length > 0;
  const lowOverlap = timeOverlapPct < 80;

  if (!hasParamDiffs && !lowOverlap) return null;

  return (
    <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 mb-4">
      <div className="flex items-start gap-3">
        <AlertTriangle className="w-5 h-5 text-amber-600 mt-0.5 flex-shrink-0" />
        <div className="flex-1 space-y-3">
          <div className="flex items-center gap-2 flex-wrap">
            {symbol && (
              <span className="text-sm font-medium text-amber-900">{symbol}</span>
            )}
            {strategyType && (
              <span className="text-sm text-amber-700">· {strategyType}</span>
            )}
            <span className="text-sm text-amber-700">对比说明</span>
          </div>

          {hasParamDiffs && (
            <div>
              <p className="text-xs text-amber-800 font-medium mb-1">参数差异：</p>
              <div className="flex flex-wrap gap-2">
                {Object.entries(paramDiffs).map(([key, vals]) => (
                  <span
                    key={key}
                    className="inline-flex items-center px-2 py-0.5 rounded text-xs bg-white border border-amber-300 text-amber-900"
                  >
                    <span className="text-red-600 font-medium">{key}:</span>
                    <span className="ml-1">
                      {String(vals.replay ?? "—")} vs {String(vals.backtest ?? "—")}
                    </span>
                  </span>
                ))}
              </div>
            </div>
          )}

          {lowOverlap && (
            <p className="text-xs text-amber-800">
              时间重叠率仅 {timeOverlapPct.toFixed(1)}%（建议 ≥ 80% 以确保可比性）
            </p>
          )}

          <div className="flex items-center gap-3 text-xs text-amber-700">
            <span className="flex items-center gap-1">
              <DataSourceBadge source={replayDataSource as "REPLAY" | "PAPER" | "BACKTEST" | "REAL" | "MOCK"} />
              <span>回放：逐bar模拟执行，可能存在滑点</span>
            </span>
            <span className="flex items-center gap-1">
              <DataSourceBadge source={backtestDataSource as "REPLAY" | "PAPER" | "BACKTEST" | "REAL" | "MOCK"} />
              <span>回测：历史收盘价执行</span>
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
