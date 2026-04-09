"use client";

import { useEffect, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Save, Play, RefreshCw, Settings2 } from "lucide-react";

// ─── Types ────────────────────────────────────────────────────────────────────
export interface DynamicSelectionConfig {
  evaluation_period: "1d" | "1w" | "1m";
  elimination_threshold: number; // 0-100 整数
  min_strategies: number;
  max_strategies: number;
  metrics_weights: {
    return_score: number;
    risk_score: number;
    stability_score: number;
    efficiency_score: number;
  };
}

export interface ConfigFormData {
  evaluation_period: "1d" | "1w" | "1m";
  elimination_threshold: number; // 0-100 整数
  min_strategies: number;
  max_strategies: number;
  weight_method: "equal" | "rank_based" | "score_based" | "risk_parity";
  elimination_ratio: number; // 0-50 for display
}

interface ConfigToolbarProps {
  onRefresh: () => void;
  onConfigSaved?: () => void;
  loading?: boolean;
}

// ─── Constants ────────────────────────────────────────────────────────────────
const DEFAULT_CONFIG: ConfigFormData = {
  evaluation_period: "1w",
  elimination_threshold: 30,
  min_strategies: 3,
  max_strategies: 10,
  weight_method: "rank_based",
  elimination_ratio: 20,
};

const WEIGHT_METHOD_OPTIONS = [
  { value: "equal", label: "等权", description: "equal" },
  { value: "rank_based", label: "排名", description: "rank_based" },
  { value: "score_based", label: "评分", description: "score_based" },
  { value: "risk_parity", label: "风险平价", description: "risk_parity" },
] as const;

// ─── Component ────────────────────────────────────────────────────────────────
export function ConfigToolbar({
  onRefresh,
  onConfigSaved,
  loading = false,
}: ConfigToolbarProps) {
  const [config, setConfig] = useState<ConfigFormData>(DEFAULT_CONFIG);
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isEvaluating, setIsEvaluating] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [toast, setToast] = useState<{
    message: string;
    type: "success" | "error";
  } | null>(null);

  // Fetch config on mount
  useEffect(() => {
    fetchConfig();
  }, []);

  // Auto-hide toast
  useEffect(() => {
    if (toast) {
      const timer = setTimeout(() => setToast(null), 3000);
      return () => clearTimeout(timer);
    }
  }, [toast]);

  const fetchConfig = async () => {
    setIsLoading(true);
    try {
      const res = await fetch("/api/v1/dynamic-selection/config");
      if (!res.ok) {
        console.warn(`获取配置失败：服务器返回 ${res.status}，使用默认配置`);
        // Keep default config
        return;
      }
      const data: DynamicSelectionConfig = await res.json();

      setConfig({
        evaluation_period: data.evaluation_period,
        elimination_threshold: data.elimination_threshold,
        min_strategies: data.min_strategies,
        max_strategies: data.max_strategies,
        weight_method: DEFAULT_CONFIG.weight_method, // API doesn't have this, use default
        elimination_ratio: DEFAULT_CONFIG.elimination_ratio, // API doesn't have this, use default
      });
    } catch (err) {
      console.warn("获取配置失败，使用默认配置:", err);
      // Keep default config
    } finally {
      setIsLoading(false);
    }
  };

  const handleSaveConfig = async () => {
    setIsSaving(true);
    try {
      const payload: DynamicSelectionConfig = {
        evaluation_period: config.evaluation_period,
        elimination_threshold: config.elimination_threshold,
        min_strategies: config.min_strategies,
        max_strategies: config.max_strategies,
        metrics_weights: {
          return_score: 0.3,
          risk_score: 0.3,
          stability_score: 0.2,
          efficiency_score: 0.2,
        },
      };

      const res = await fetch("/api/v1/dynamic-selection/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const errorMsg = `配置保存失败：服务器返回 ${res.status}`;
        console.warn(errorMsg);
        setToast({ message: errorMsg, type: "error" });
        return;
      }

      setToast({ message: "配置保存成功", type: "success" });
      onConfigSaved?.();
    } catch (err) {
      const errorMsg = "后端服务未连接，配置保存失败";
      console.warn("Failed to save config:", err);
      setToast({ message: errorMsg, type: "error" });
    } finally {
      setIsSaving(false);
    }
  };

  const handleEvaluate = async () => {
    setIsEvaluating(true);
    try {
      const res = await fetch("/api/v1/dynamic-selection/evaluate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ force_recalculate: true }),
      });

      if (!res.ok) {
        const errorMsg = `评估触发失败：服务器返回 ${res.status}`;
        console.warn(errorMsg);
        setToast({ message: errorMsg, type: "error" });
        return;
      }

      setToast({ message: "评估已触发，数据刷新中...", type: "success" });
      setDialogOpen(false);
      onRefresh();
    } catch (err) {
      const errorMsg = "后端服务未连接，评估触发失败";
      console.warn("Failed to trigger evaluation:", err);
      setToast({ message: errorMsg, type: "error" });
    } finally {
      setIsEvaluating(false);
    }
  };

  const updateConfig = <K extends keyof ConfigFormData>(
    key: K,
    value: ConfigFormData[K]
  ) => {
    setConfig((prev) => ({ ...prev, [key]: value }));
  };

  return (
    <Card className="bg-slate-900/50 border-slate-700/50">
      <CardContent className="p-4">
        <div className="flex flex-col gap-4">
          {/* Header */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Settings2 className="w-4 h-4 text-blue-400" />
              <h3 className="text-sm font-medium text-slate-200">
                动态选择配置
              </h3>
            </div>
            <div className="flex items-center gap-2">
              {/* Toast notification */}
              {toast && (
                <span
                  className={`text-xs px-2 py-1 rounded ${
                    toast.type === "success"
                      ? "bg-emerald-500/10 text-emerald-400"
                      : "bg-red-500/10 text-red-400"
                  }`}
                >
                  {toast.message}
                </span>
              )}

              <Button
                variant="outline"
                size="sm"
                onClick={handleSaveConfig}
                disabled={isSaving || isLoading}
                className="border-slate-700 text-slate-300 hover:text-white bg-slate-800/50 h-8"
              >
                <Save className="w-3.5 h-3.5 mr-1.5" />
                保存配置
              </Button>

              <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
                <DialogTrigger asChild>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={isEvaluating}
                    className="border-blue-500/30 text-blue-400 hover:text-blue-300 hover:bg-blue-500/10 bg-blue-500/5 h-8"
                  >
                    <Play className="w-3.5 h-3.5 mr-1.5" />
                    手动触发评估
                  </Button>
                </DialogTrigger>
                <DialogContent className="bg-slate-900 border-slate-700">
                  <DialogHeader>
                    <DialogTitle className="text-slate-100">
                      确认触发评估
                    </DialogTitle>
                    <DialogDescription className="text-slate-400">
                      这将立即重新计算所有策略的评分和权重分配。是否继续？
                    </DialogDescription>
                  </DialogHeader>
                  <DialogFooter className="gap-2">
                    <Button
                      variant="outline"
                      onClick={() => setDialogOpen(false)}
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

              <Button
                variant="outline"
                size="sm"
                onClick={onRefresh}
                disabled={loading}
                className="border-slate-700 text-slate-300 hover:text-white bg-slate-800/50 h-8"
              >
                <RefreshCw
                  className={`w-3.5 h-3.5 mr-1.5 ${loading ? "animate-spin" : ""}`}
                />
                刷新数据
              </Button>
            </div>
          </div>

          {/* Config Form */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
            {/* Evaluation Period */}
            <div className="space-y-2">
              <Label className="text-xs text-slate-400">评估周期</Label>
              <Select
                value={config.evaluation_period}
                onValueChange={(value: "1d" | "1w" | "1m") =>
                  updateConfig("evaluation_period", value)
                }
                disabled={isLoading}
              >
                <SelectTrigger className="bg-slate-800/50 border-slate-700 text-slate-200 h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-slate-800 border-slate-700">
                  <SelectItem value="1d" className="text-slate-200 text-xs">
                    每天 (1d)
                  </SelectItem>
                  <SelectItem value="1w" className="text-slate-200 text-xs">
                    每周 (1w)
                  </SelectItem>
                  <SelectItem value="1m" className="text-slate-200 text-xs">
                    每月 (1m)
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Elimination Threshold */}
            <div className="space-y-2">
              <Label className="text-xs text-slate-400">
                淘汰阈值 ({config.elimination_threshold}%)
              </Label>
              <Slider
                value={[config.elimination_threshold]}
                onValueChange={([value]) =>
                  updateConfig("elimination_threshold", value)
                }
                min={0}
                max={100}
                step={1}
                disabled={isLoading}
                className="pt-2"
              />
            </div>

            {/* Min Strategies */}
            <div className="space-y-2">
              <Label className="text-xs text-slate-400">最少保留</Label>
              <input
                type="number"
                value={config.min_strategies}
                onChange={(e) =>
                  updateConfig("min_strategies", parseInt(e.target.value) || 1)
                }
                min={1}
                max={20}
                disabled={isLoading}
                className="w-full h-8 px-2 text-xs bg-slate-800/50 border border-slate-700 rounded-md text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500/50"
              />
            </div>

            {/* Max Strategies */}
            <div className="space-y-2">
              <Label className="text-xs text-slate-400">最多保留</Label>
              <input
                type="number"
                value={config.max_strategies}
                onChange={(e) =>
                  updateConfig("max_strategies", parseInt(e.target.value) || 1)
                }
                min={1}
                max={50}
                disabled={isLoading}
                className="w-full h-8 px-2 text-xs bg-slate-800/50 border border-slate-700 rounded-md text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500/50"
              />
            </div>

            {/* Weight Method */}
            <div className="space-y-2">
              <Label className="text-xs text-slate-400">权重分配方法</Label>
              <RadioGroup
                value={config.weight_method}
                onValueChange={(value: ConfigFormData["weight_method"]) =>
                  updateConfig("weight_method", value)
                }
                disabled={isLoading}
                className="flex flex-wrap gap-2"
              >
                {WEIGHT_METHOD_OPTIONS.map((option) => (
                  <div key={option.value} className="flex items-center gap-1">
                    <RadioGroupItem
                      value={option.value}
                      id={`weight-${option.value}`}
                      className="border-slate-600 text-blue-500"
                    />
                    <Label
                      htmlFor={`weight-${option.value}`}
                      className="text-xs text-slate-300 cursor-pointer"
                    >
                      {option.label}
                    </Label>
                  </div>
                ))}
              </RadioGroup>
            </div>

            {/* Elimination Ratio */}
            <div className="space-y-2">
              <Label className="text-xs text-slate-400">
                末位淘汰比例 ({config.elimination_ratio}%)
              </Label>
              <Slider
                value={[config.elimination_ratio]}
                onValueChange={([value]) =>
                  updateConfig("elimination_ratio", value)
                }
                min={0}
                max={50}
                step={1}
                disabled={isLoading}
                className="pt-2"
              />
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
