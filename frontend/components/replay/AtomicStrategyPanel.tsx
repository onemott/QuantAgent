"use client";

import { useState, useCallback, useMemo, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Slider } from "@/components/ui/slider";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Plus, Trash2, Settings2, AlertCircle, ChevronDown, ChevronUp } from "lucide-react";

// ─── Types ────────────────────────────────────────────────────────────────────
export interface StrategyTemplate {
  id: string;
  name: string;
  description: string;
  params: {
    key: string;
    label: string;
    type: "int" | "float";
    default: number;
    min: number;
    max: number;
    step?: number;
    description?: string;
  }[];
  supports_replay?: boolean;
}

export interface AtomicStrategyConfig {
  strategy_id: string;
  strategy_type: string;
  params: Record<string, any>;
}

export interface AtomicStrategyPanelProps {
  strategies: AtomicStrategyConfig[];
  onChange: (strategies: AtomicStrategyConfig[]) => void;
  templates: StrategyTemplate[];
  evaluationPeriod?: number;
  onEvaluationPeriodChange?: (value: number) => void;
  weightMethod?: string;
  onWeightMethodChange?: (value: string) => void;
  compositionThreshold?: number;
  onCompositionThresholdChange?: (value: number) => void;
  eliminationRule?: {
    min_score_threshold: number;
    elimination_ratio: number;
    min_consecutive_low: number;
    low_score_threshold: number;
    min_strategies: number;
  };
  onEliminationRuleChange?: (rule: {
    min_score_threshold: number;
    elimination_ratio: number;
    min_consecutive_low: number;
    low_score_threshold: number;
    min_strategies: number;
  }) => void;
  perStrategyCapital?: number;
  onPerStrategyCapitalChange?: (value: number) => void;
  interval?: string;
}

const WEIGHT_METHOD_OPTIONS = [
  { value: "equal", label: "等权", description: "equal - 平均分配权重" },
  { value: "rank_based", label: "排名", description: "rank_based - 按排名分配权重" },
  { value: "score_based", label: "评分", description: "score_based - 按评分分配权重" },
  { value: "risk_parity", label: "风险平价", description: "risk_parity - 风险平价分配" },
] as const;

const MAX_STRATEGIES = 8;
const MIN_STRATEGIES = 2;

export function AtomicStrategyPanel({
  strategies,
  onChange,
  templates,
  evaluationPeriod = 1440,
  onEvaluationPeriodChange,
  weightMethod = "score_based",
  onWeightMethodChange,
  compositionThreshold = 0.5,
  onCompositionThresholdChange,
  eliminationRule = {
    min_score_threshold: 40.0,
    elimination_ratio: 0.2,
    min_consecutive_low: 3,
    low_score_threshold: 30.0,
    min_strategies: 2,
  },
  onEliminationRuleChange,
  perStrategyCapital,
  onPerStrategyCapitalChange,
  interval = "1m",
}: AtomicStrategyPanelProps) {
  const [showGlobalConfig, setShowGlobalConfig] = useState(false);

  // Interval 到分钟的映射
  const INTERVAL_MINUTES: Record<string, number> = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
  };

  // 计算并格式化时间跨度
  const formatEvaluationTime = useMemo(() => {
    const intervalMinutes = INTERVAL_MINUTES[interval] || 1;
    const totalMinutes = evaluationPeriod * intervalMinutes;

    if (totalMinutes < 60) {
      return `${totalMinutes} 分钟`;
    } else if (totalMinutes < 1440) {
      return `约 ${Math.round(totalMinutes / 60)} 小时`;
    } else if (totalMinutes < 43200) {
      return `约 ${Math.round(totalMinutes / 1440)} 天`;
    } else {
      return `约 ${Math.round(totalMinutes / 43200)} 月`;
    }
  }, [evaluationPeriod, interval]);

  // Filter valid templates (exclude dynamic_selection itself or templates not supporting replay)
  const validTemplates = useMemo(() => {
    return templates.filter(t => t.id !== "dynamic_selection");
  }, [templates]);

  // Generate unique strategy ID
  const generateStrategyId = useCallback((type: string, index: number) => {
    return `ds_${type}_${index}`;
  }, []);

  // Get next available index for a type (based on all existing strategy IDs to avoid conflicts)
  const getNextIndex = useCallback((type: string) => {
    const usedIds = new Set(strategies.map(s => s.strategy_id));
    let index = 1;
    while (usedIds.has(`ds_${type}_${index}`)) {
      index++;
    }
    return index;
  }, [strategies]);

  // Add new strategy
  const handleAddStrategy = useCallback(() => {
    if (strategies.length >= MAX_STRATEGIES || validTemplates.length === 0) return;

    const template = validTemplates[0];
    const type = template.id;
    const index = getNextIndex(type);
    
    const defaultParams: Record<string, number> = {};
    template.params.forEach(p => {
      defaultParams[p.key] = p.default;
    });

    const newStrategy: AtomicStrategyConfig = {
      strategy_id: generateStrategyId(type, index),
      strategy_type: type,
      params: defaultParams,
    };
    onChange([...strategies, newStrategy]);
  }, [strategies, onChange, generateStrategyId, getNextIndex, validTemplates]);

  // Remove strategy
  const handleRemoveStrategy = useCallback((index: number) => {
    if (strategies.length <= MIN_STRATEGIES) return;
    const newStrategies = strategies.filter((_, i) => i !== index);
    onChange(newStrategies);
  }, [strategies, onChange]);

  // Update strategy type
  const handleTypeChange = useCallback((index: number, newType: string) => {
    const newStrategies = [...strategies];
    const template = validTemplates.find(t => t.id === newType);
    const defaultParams: Record<string, number> = {};
    
    if (template) {
      template.params.forEach(p => {
        defaultParams[p.key] = p.default;
      });
    }

    const typeIndex = getNextIndex(newType);
    newStrategies[index] = {
      ...newStrategies[index],
      strategy_id: generateStrategyId(newType, typeIndex),
      strategy_type: newType,
      params: defaultParams,
    };
    
    onChange(newStrategies);
  }, [strategies, onChange, generateStrategyId, getNextIndex, validTemplates]);

  // Update strategy ID
  const handleIdChange = useCallback((index: number, newId: string) => {
    const newStrategies = [...strategies];
    newStrategies[index] = { ...newStrategies[index], strategy_id: newId };
    onChange(newStrategies);
  }, [strategies, onChange]);

  // Update param value
  const handleParamChange = useCallback((
    strategyIndex: number,
    paramKey: string,
    value: number
  ) => {
    const newStrategies = [...strategies];
    newStrategies[strategyIndex] = {
      ...newStrategies[strategyIndex],
      params: {
        ...newStrategies[strategyIndex].params,
        [paramKey]: value
      }
    };
    onChange(newStrategies);
  }, [strategies, onChange]);

  // Validation - computed during render
  const errors = useMemo(() => {
    const newErrors: string[] = [];

    if (strategies.length < MIN_STRATEGIES) {
      newErrors.push(`至少需要 ${MIN_STRATEGIES} 个原子策略`);
    }

    const ids = strategies.map((s) => s.strategy_id);
    const duplicates = ids.filter((item, index) => ids.indexOf(item) !== index);
    if (duplicates.length > 0) {
      newErrors.push(`存在重复的策略 ID: ${[...new Set(duplicates)].join(", ")}`);
    }

    const types = new Set(strategies.map((s) => s.strategy_type));
    if (types.size === 1 && strategies.length > 1) {
      newErrors.push("建议配置不同类型的策略以获得更好的分散效果");
    }

    return newErrors;
  }, [strategies]);

  const canAdd = strategies.length < MAX_STRATEGIES;
  const canRemove = strategies.length > MIN_STRATEGIES;

  return (
    <Card className="bg-slate-900 border-slate-700/50">
      <CardHeader className="pb-3">
        <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
          <div className="w-6 h-6 bg-indigo-500/10 rounded flex items-center justify-center border border-indigo-500/20">
            <Settings2 className="w-3.5 h-3.5 text-indigo-400" />
          </div>
          动态选择策略配置
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Strategy List */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <Label className="text-xs text-slate-400">
              原子策略列表
              <span className="text-slate-500 ml-1">
                ({strategies.length}/{MAX_STRATEGIES})
              </span>
            </Label>
            <Button
              variant="outline"
              size="sm"
              onClick={handleAddStrategy}
              disabled={!canAdd}
              className="h-7 px-2 text-xs border-slate-700 text-slate-300 hover:text-white bg-slate-800/50 disabled:opacity-50"
            >
              <Plus className="w-3.5 h-3.5 mr-1" />
              添加策略
            </Button>
          </div>

          {strategies.map((strategy, index) => {
            const template = validTemplates.find(t => t.id === strategy.strategy_type);
            return (
              <Card
                key={`${strategy.strategy_id}-${index}`}
                className="bg-slate-800/50 border-slate-700/50"
              >
                <CardContent className="p-3 space-y-3">
                  {/* Strategy Header */}
                  <div className="flex items-center gap-2">
                    <Badge
                      variant="outline"
                      className="bg-slate-700/50 border-slate-600 text-slate-300 text-xs"
                    >
                      #{index + 1}
                    </Badge>
                    
                    {/* Strategy Type Select */}
                    <Select
                      value={strategy.strategy_type}
                      onValueChange={(value) => handleTypeChange(index, value)}
                    >
                      <SelectTrigger className="flex-1 h-8 text-xs bg-slate-800/50 border-slate-700 text-slate-200">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent className="bg-slate-800 border-slate-700">
                        {validTemplates.map((type) => (
                          <SelectItem
                            key={type.id}
                            value={type.id}
                            className="text-slate-200 text-xs"
                          >
                            <div className="flex flex-col">
                              <span>{type.name}</span>
                              <span className="text-[10px] text-slate-500">
                                {type.description}
                              </span>
                            </div>
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>

                    {/* Delete Button */}
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleRemoveStrategy(index)}
                      disabled={!canRemove}
                      className="h-8 w-8 p-0 text-slate-500 hover:text-red-400 hover:bg-red-500/10 disabled:opacity-30"
                    >
                      <Trash2 className="w-4 h-4" />
                    </Button>
                  </div>

                  {/* Strategy ID Input */}
                  <div className="flex items-center gap-2">
                    <Label className="text-xs text-slate-500 w-16 shrink-0">
                      策略 ID
                    </Label>
                    <Input
                      value={strategy.strategy_id}
                      onChange={(e: React.ChangeEvent<HTMLInputElement>) => handleIdChange(index, e.target.value)}
                      className="h-7 text-xs bg-slate-800/50 border-slate-700 text-slate-200 font-mono"
                      placeholder="输入策略 ID"
                    />
                  </div>

                  {/* Params Grid - Slider style reused from page.tsx */}
                  {template && template.params.length > 0 && (
                    <div className="space-y-4 pt-2 border-t border-slate-700/50">
                      {template.params.map(p => (
                        <div key={p.key}>
                          <div className="flex items-center justify-between mb-1.5">
                            <label className="text-[10px] text-slate-300">{p.label}</label>
                            <span className="text-[10px] font-mono text-purple-400 bg-purple-500/10 px-1.5 py-0.5 rounded">
                              {strategy.params[p.key] ?? p.default}
                            </span>
                          </div>
                          <input
                            type="range"
                            min={p.min}
                            max={p.max}
                            step={p.step ?? (p.type === "int" ? 1 : 0.5)}
                            value={strategy.params[p.key] ?? p.default}
                            onChange={e => handleParamChange(index, p.key, p.type === "int" ? parseInt(e.target.value) : parseFloat(e.target.value))}
                            className="w-full h-1 bg-slate-700 rounded-full appearance-none cursor-pointer accent-purple-500"
                          />
                          <div className="flex justify-between mt-0.5">
                            <span className="text-[8px] text-slate-600">{p.min}</span>
                            <span className="text-[8px] text-slate-600">{p.max}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </div>

        {/* Global Configuration */}
        <div className="border border-slate-700/50 rounded-lg overflow-hidden mt-4">
          <button
            onClick={() => setShowGlobalConfig(!showGlobalConfig)}
            className="w-full px-3 py-2 bg-slate-800/50 hover:bg-slate-800 text-left flex items-center justify-between transition-all"
          >
            <span className="text-xs text-slate-300 font-medium">高级配置 (动态选择参数)</span>
            {showGlobalConfig ? (
              <ChevronUp className="w-4 h-4 text-slate-400" />
            ) : (
              <ChevronDown className="w-4 h-4 text-slate-400" />
            )}
          </button>

          {showGlobalConfig && (
            <div className="p-3 space-y-4 bg-slate-900/50 border-t border-slate-700/50">
              {/* Evaluation Period */}
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label className="text-xs text-slate-500">评估间隔 (evaluation_period)</Label>
                  <span className="text-xs font-mono text-indigo-400 bg-indigo-500/10 px-2 py-0.5 rounded">
                    {evaluationPeriod} 根 K 线
                  </span>
                </div>
                <Input
                  type="number"
                  value={evaluationPeriod}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                    onEvaluationPeriodChange?.(parseInt(e.target.value) || 1440)
                  }
                  min={1}
                  className="h-8 text-xs bg-slate-800/50 border-slate-700 text-slate-200"
                  placeholder="根 K 线触发一次评估"
                />
                <p className="text-[10px] text-slate-600">
                  每 {evaluationPeriod} 根 K 线触发一次评估（{formatEvaluationTime} @ {interval} K线）
                </p>
              </div>

              {/* Weight Method */}
              <div className="space-y-2">
                <Label className="text-xs text-slate-500">权重分配方法 (weight_method)</Label>
                <Select
                  value={weightMethod}
                  onValueChange={(value) => onWeightMethodChange?.(value)}
                >
                  <SelectTrigger className="h-8 text-xs bg-slate-800/50 border-slate-700 text-slate-200">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-slate-800 border-slate-700">
                    {WEIGHT_METHOD_OPTIONS.map((option) => (
                      <SelectItem
                        key={option.value}
                        value={option.value}
                        className="text-slate-200 text-xs"
                      >
                        <div className="flex flex-col">
                          <span>{option.label}</span>
                          <span className="text-[10px] text-slate-500">
                            {option.description}
                          </span>
                        </div>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* Composition Threshold */}
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label className="text-xs text-slate-500">组合阈值 (composition_threshold)</Label>
                  <span className="text-xs font-mono text-indigo-400 bg-indigo-500/10 px-2 py-0.5 rounded">
                    {(compositionThreshold * 100).toFixed(0)}%
                  </span>
                </div>
                <Slider
                  value={[compositionThreshold]}
                  onValueChange={([value]) =>
                    onCompositionThresholdChange?.(value)
                  }
                  min={0.1}
                  max={0.9}
                  step={0.05}
                  className="pt-1"
                />
                <p className="text-[10px] text-slate-600">
                  策略入选组合的最低评分阈值
                </p>
              </div>

              {/* Elimination Rule */}
              <div className="space-y-3 pt-2 border-t border-slate-700/50">
                <Label className="text-xs text-slate-500">淘汰规则 (elimination_rule)</Label>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label className="text-[10px] text-slate-400">最低分阈值 (min_score_threshold)</Label>
                    <Input
                      type="number"
                      value={eliminationRule.min_score_threshold}
                      onChange={(e) =>
                        onEliminationRuleChange?.({
                          ...eliminationRule,
                          min_score_threshold: Math.max(0, Math.min(100, parseFloat(e.target.value) || 0)),
                        })
                      }
                      className="h-7 text-xs bg-slate-800/50 border-slate-700 text-slate-200"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-[10px] text-slate-400">淘汰比例 (elimination_ratio)</Label>
                    <Input
                      type="number"
                      step="0.1"
                      value={eliminationRule.elimination_ratio}
                      onChange={(e) =>
                        onEliminationRuleChange?.({
                          ...eliminationRule,
                          elimination_ratio: Math.max(0, Math.min(1, parseFloat(e.target.value) || 0)),
                        })
                      }
                      className="h-7 text-xs bg-slate-800/50 border-slate-700 text-slate-200"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-[10px] text-slate-400">连续低分次数 (min_consecutive_low)</Label>
                    <Input
                      type="number"
                      value={eliminationRule.min_consecutive_low}
                      onChange={(e) =>
                        onEliminationRuleChange?.({
                          ...eliminationRule,
                          min_consecutive_low: Math.max(1, Math.floor(parseInt(e.target.value) || 1)),
                        })
                      }
                      className="h-7 text-xs bg-slate-800/50 border-slate-700 text-slate-200"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-[10px] text-slate-400">保留的最少策略数 (min_strategies)</Label>
                    <Input
                      type="number"
                      value={eliminationRule.min_strategies}
                      onChange={(e) =>
                        onEliminationRuleChange?.({
                          ...eliminationRule,
                          min_strategies: Math.max(2, Math.floor(parseInt(e.target.value) || 2)),
                        })
                      }
                      className="h-7 text-xs bg-slate-800/50 border-slate-700 text-slate-200"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-[10px] text-slate-400">低分判定阈值 (low_score_threshold)</Label>
                    <Input
                      type="number"
                      value={eliminationRule.low_score_threshold}
                      onChange={(e) =>
                        onEliminationRuleChange?.({
                          ...eliminationRule,
                          low_score_threshold: Math.max(0, Math.min(100, parseFloat(e.target.value) || 0)),
                        })
                      }
                      className="h-7 text-xs bg-slate-800/50 border-slate-700 text-slate-200"
                    />
                  </div>
                </div>
              </div>

              {/* Per Strategy Capital */}
              <div className="space-y-2">
                <Label className="text-xs text-slate-500">每策略资金 (per_strategy_capital)</Label>
                <Input
                  type="number"
                  value={perStrategyCapital || ""}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => {
                    const val = e.target.value ? parseFloat(e.target.value) : undefined;
                    onPerStrategyCapitalChange?.(val as number);
                  }}
                  min={0}
                  placeholder="留空则自动均分"
                  className="h-8 text-xs bg-slate-800/50 border-slate-700 text-slate-200"
                />
                <p className="text-[10px] text-slate-600">
                  指定每个策略的固定资金，留空则根据权重自动分配
                </p>
              </div>
            </div>
          )}
        </div>

        {/* Validation Errors */}
        {errors.length > 0 && (
          <div className="space-y-1">
            {errors.map((error, idx) => (
              <div
                key={idx}
                className={`flex items-center gap-1.5 text-xs ${
                  error.includes("建议")
                    ? "text-amber-400"
                    : "text-red-400"
                }`}
              >
                <AlertCircle className="w-3.5 h-3.5 shrink-0" />
                <span>{error}</span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default AtomicStrategyPanel;