"use client";

import { useEffect, useRef, useMemo } from "react";
import { createChart, LineSeries, IChartApi, ISeriesApi, Time } from "lightweight-charts";

interface CompositionCompareChartProps {
  equityCurves: Record<string, { t: string; v: number }[]>;
  initialCapital: number;
  height?: number;
}

// Color scheme for composition types
const COMPOSITION_COLORS: Record<string, { color: string; lineWidth: 1 | 2 | 3 | 4; lineStyle?: number }> = {
  weighted: { color: "#3b82f6", lineWidth: 3 },  // Blue
  voting: { color: "#a855f7", lineWidth: 3 },    // Purple
};

// Color scheme for atomic strategies (in order)
const ATOMIC_COLORS = [
  { color: "#f97316", lineStyle: 2 },  // Orange
  { color: "#22c55e", lineStyle: 2 },  // Green
  { color: "#ef4444", lineStyle: 2 },  // Red
  { color: "#eab308", lineStyle: 2 },  // Yellow
  { color: "#06b6d4", lineStyle: 2 },  // Cyan
  { color: "#ec4899", lineStyle: 2 },  // Pink
  { color: "#8b5cf6", lineStyle: 2 },  // Light Purple
  { color: "#14b8a6", lineStyle: 2 },  // Teal
];

// Strategy name mapping
const STRATEGY_NAMES: Record<string, string> = {
  weighted: "加权组合",
  voting: "投票组合",
  ma: "MA策略",
  rsi: "RSI策略",
  boll: "BOLL策略",
  macd: "MACD策略",
  kdj: "KDJ策略",
  atr: "ATR策略",
};

// ─── Helper: Dedupe and sort data by time ────────────────────────────────────
function dedupeAndSort<T extends { time: Time }>(data: T[]): T[] {
  if (data.length === 0) return data;
  const map = new Map<Time, T>();
  for (const item of data) {
    map.set(item.time, item);
  }
  return Array.from(map.values()).sort(
    (a, b) => (a.time as number) - (b.time as number)
  );
}

// ─── Helper: Strict ascending filter ─────────────────────────────────────────
function strictAscFilter<T extends { time: Time }>(data: T[]): T[] {
  if (data.length <= 1) return data;
  const result = [data[0]];
  for (let i = 1; i < data.length; i++) {
    if ((data[i].time as number) > (result[result.length - 1].time as number)) {
      result.push(data[i]);
    }
  }
  return result;
}

// ─── Helper: Combined dedupe, sort, and strict filter ────────────────────────
function prepareChartData<T extends { time: Time }>(data: T[]): T[] {
  return strictAscFilter(dedupeAndSort(data));
}

export function CompositionCompareChart({
  equityCurves,
  initialCapital,
  height = 320,
}: CompositionCompareChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRefs = useRef<Map<string, ISeriesApi<"Line">>>(new Map());
  // Compute isEmpty using useMemo instead of useState + useEffect
  const isEmpty = useMemo(() => {
    return !Object.values(equityCurves || {}).some(d => d && d.length > 0);
  }, [equityCurves]);

  // Get ordered strategy keys (compositions first, then atomic strategies)
  const getOrderedKeys = () => {
    const keys = Object.keys(equityCurves || {});
    const compositionKeys = keys.filter(k => k === "weighted" || k === "voting");
    const atomicKeys = keys.filter(k => k !== "weighted" && k !== "voting");
    return [...compositionKeys, ...atomicKeys];
  };

  // Initialize chart
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: "#0f172a" },
        textColor: "#94a3b8",
      },
      grid: {
        vertLines: { color: "#1e293b" },
        horzLines: { color: "#1e293b" },
      },
      crosshair: {
        mode: 1,
        vertLine: {
          color: "#6366f1",
          width: 1,
          style: 2,
        },
        horzLine: {
          color: "#6366f1",
          width: 1,
          style: 2,
        },
      },
      rightPriceScale: {
        borderColor: "#334155",
        scaleMargins: {
          top: 0.1,
          bottom: 0.1,
        },
      },
      timeScale: {
        borderColor: "#334155",
        timeVisible: true,
        secondsVisible: false,
      },
      handleScale: false,
      handleScroll: false,
    });

    chartRef.current = chart;

    // Handle resize
    const handleResize = () => {
      if (containerRef.current && chartRef.current) {
        chart.applyOptions({
          width: containerRef.current.clientWidth,
        });
      }
    };

    window.addEventListener("resize", handleResize);
    handleResize();

    return () => {
      window.removeEventListener("resize", handleResize);
      try {
        if (chartRef.current && containerRef.current && document.body.contains(containerRef.current)) {
          chartRef.current.remove();
        }
      } catch {
        console.warn("Composition chart removal error");
      }
      chartRef.current = null;
      seriesRefs.current.clear();
    };
  }, []);

  // Create series and update data
  useEffect(() => {
    if (!chartRef.current || !equityCurves) return;

    // Clear existing series
    seriesRefs.current.forEach((series) => {
      try {
        chartRef.current?.removeSeries(series);
      } catch {
        // Series might already be removed
      }
    });
    seriesRefs.current.clear();

    const orderedKeys = getOrderedKeys();
    let atomicIndex = 0;

    for (const key of orderedKeys) {
      const data = equityCurves[key];
      if (!data || data.length === 0) continue;

      const isComposition = key === "weighted" || key === "voting";
      let seriesOptions: {
        color: string;
        lineWidth: 1 | 2 | 3 | 4;
        lineStyle?: number;
        title: string;
      };

      if (isComposition && COMPOSITION_COLORS[key]) {
        seriesOptions = {
          color: COMPOSITION_COLORS[key].color,
          lineWidth: COMPOSITION_COLORS[key].lineWidth,
          title: STRATEGY_NAMES[key] || key.toUpperCase(),
        };
      } else {
        // Atomic strategy
        const colorConfig = ATOMIC_COLORS[atomicIndex % ATOMIC_COLORS.length];
        seriesOptions = {
          color: colorConfig.color,
          lineWidth: 2,
          lineStyle: colorConfig.lineStyle,
          title: STRATEGY_NAMES[key] || key.toUpperCase(),
        };
        atomicIndex++;
      }

      const series = chartRef.current.addSeries(LineSeries, seriesOptions);
      seriesRefs.current.set(key, series);

      // Convert and prepare data
      const rawPoints = data.map(d => ({
        time: (new Date(d.t).getTime() / 1000) as Time,
        value: d.v,
      }));
      const points = prepareChartData(rawPoints);
      series.setData(points);
    }

    // Add initial capital reference line on first series
    const firstSeries = seriesRefs.current.values().next().value;
    if (firstSeries) {
      firstSeries.createPriceLine({
        price: initialCapital,
        color: "#475569",
        lineWidth: 1,
        lineStyle: 2,
        axisLabelVisible: true,
        title: "初始资金",
      });
    }

    chartRef.current.timeScale().fitContent();
  }, [equityCurves, initialCapital]);

  // Get legend items - use independent counter for atomic strategies
  const legendItems = (() => {
    let atomicCounter = 0;
    return getOrderedKeys().map((key) => {
      const isComposition = key === "weighted" || key === "voting";
      let color: string;
      let isDashed = false;
      let lineWidth = 2;

      if (isComposition && COMPOSITION_COLORS[key]) {
        color = COMPOSITION_COLORS[key].color;
        lineWidth = 3;
      } else {
        const colorConfig = ATOMIC_COLORS[atomicCounter % ATOMIC_COLORS.length];
        color = colorConfig.color;
        isDashed = true;
        lineWidth = 1.5;
        atomicCounter++;
      }

      return {
        key,
        name: STRATEGY_NAMES[key] || key.toUpperCase(),
        color,
        isDashed,
        lineWidth,
      };
    });
  })();

  return (
    <div className="relative">
      <div ref={containerRef} className="w-full" style={{ height: `${height}px` }} />
      
      {/* Legend - Top Left */}
      {!isEmpty && (
        <div className="absolute top-2 left-3 flex flex-wrap items-center gap-x-4 gap-y-1 pointer-events-none max-w-[80%]">
          {legendItems.map((item) => (
            <div key={item.key} className="flex items-center gap-1.5">
              <div
                className="rounded"
                style={{
                  width: item.lineWidth === 3 ? '16px' : '12px',
                  height: item.lineWidth === 3 ? '3px' : '2px',
                  borderStyle: item.isDashed ? 'dashed' : 'solid',
                  ...(item.isDashed ? {
                    borderTop: `2px dashed ${item.color}`,
                    background: 'none'
                  } : {
                    backgroundColor: item.color
                  })
                }}
              />
              <span className="text-[10px] text-slate-400 whitespace-nowrap">{item.name}</span>
            </div>
          ))}
        </div>
      )}

      {/* Initial Capital Indicator - Top Right */}
      {!isEmpty && (
        <div className="absolute top-2 right-3 text-right pointer-events-none">
          <div className="text-[10px] text-slate-500">初始资金</div>
          <div className="text-xs font-bold font-mono text-slate-400">
            ${initialCapital.toLocaleString()}
          </div>
        </div>
      )}

      {/* Empty state */}
      {isEmpty && (
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="text-center text-slate-500">
            <div className="text-sm">暂无数据</div>
            <div className="text-[10px] text-slate-600 mt-1">运行组合对比后将显示权益曲线</div>
          </div>
        </div>
      )}
    </div>
  );
}

export default CompositionCompareChart;
