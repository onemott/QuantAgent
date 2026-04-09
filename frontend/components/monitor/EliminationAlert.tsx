"use client";

import { AlertTriangle, Play } from "lucide-react";
import { Button } from "@/components/ui/button";

// ─── Types ────────────────────────────────────────────────────────────────────
export interface DimensionScore {
  subject: string;
  score: number;
  fullMark: number;
}

interface EliminationAlertProps {
  dimensions: DimensionScore[];
  threshold?: number;
  onEvaluate?: () => void;
}

// ─── Component ────────────────────────────────────────────────────────────────
export function EliminationAlert({
  dimensions,
  threshold = 40,
  onEvaluate,
}: EliminationAlertProps) {
  // Find strategies with score below threshold
  const lowScoreStrategies = dimensions.filter(
    (d) => d.score < threshold
  );

  if (lowScoreStrategies.length === 0) {
    return null;
  }

  return (
    <div className="bg-red-500/10 border border-red-500/20 rounded-lg px-4 py-3">
      <div className="flex items-start gap-3">
        <AlertTriangle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />
        <div className="flex-1 min-w-0">
          <div className="flex flex-col gap-2">
            {lowScoreStrategies.map((strategy) => (
              <p key={strategy.subject} className="text-sm text-red-400">
                ⚠️ 警告：策略 {strategy.subject} 综合得分 {strategy.score}{" "}
                分，已低于淘汰阈值（{threshold}分），建议立即评估
              </p>
            ))}
          </div>
        </div>
        {onEvaluate && (
          <Button
            variant="outline"
            size="sm"
            onClick={onEvaluate}
            className="border-red-500/30 text-red-400 hover:text-red-300 hover:bg-red-500/10 bg-red-500/5 h-8 flex-shrink-0"
          >
            <Play className="w-3.5 h-3.5 mr-1.5" />
            立即评估
          </Button>
        )}
      </div>
    </div>
  );
}
