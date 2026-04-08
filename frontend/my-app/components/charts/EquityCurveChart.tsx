"use client";

import { useEffect, useRef, useState, useMemo } from "react";
import { createChart, LineSeries, createSeriesMarkers, IChartApi, ISeriesApi, Time } from "lightweight-charts";

export interface TradeMarker {
  time: string;
  price: number;
  side: "BUY" | "SELL";
  quantity?: number;
  pnl?: number | null;
}

export interface WindowBoundary {
  time: string;
  label: string;
  color?: string;
}

interface EquityCurveChartProps {
  data: { t: string; v: number }[];
  baselineData?: { t: string; v: number }[];
  markers?: TradeMarker[];
  windowBoundaries?: WindowBoundary[];
  initialCapital: number;
  height?: number;
  showLegend?: boolean;
}

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

export function EquityCurveChart({
  data,
  baselineData = [],
  markers = [],
  windowBoundaries = [],
  initialCapital,
  height = 280,
  showLegend = true,
}: EquityCurveChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const baselineRef = useRef<ISeriesApi<"Line"> | null>(null);
  const [isEmpty, setIsEmpty] = useState(true);

  // Initialize chart
  useEffect(() => {
    if (!containerRef.current) return;
    
    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: "transparent" },
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

    // Create main series (strategy equity)
    const lineSeries = chart.addSeries(LineSeries, {
      color: "#6366f1",
      lineWidth: 2,
      title: "策略权益",
    });

    // Create baseline series (buy and hold)
    const baselineSeries = chart.addSeries(LineSeries, {
      color: "#64748b",
      lineWidth: 1,
      lineStyle: 2, // dashed
      title: "买入持有",
    });

    chartRef.current = chart;
    seriesRef.current = lineSeries;
    baselineRef.current = baselineSeries;

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
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      baselineRef.current = null;
    };
  }, []);

  // Update main data
  useEffect(() => {
    if (!seriesRef.current || !chartRef.current || !data.length) return;
    
    setIsEmpty(data.length === 0);
    
    const rawPoints = data.map(d => ({ 
      time: (new Date(d.t).getTime() / 1000) as Time, 
      value: d.v 
    }));
    const points = prepareChartData(rawPoints);
    
    seriesRef.current.setData(points);
    chartRef.current.timeScale().fitContent();
  }, [data]);

  // Update baseline data
  useEffect(() => {
    if (!baselineRef.current || !baselineData.length) return;
    
    const rawPoints = baselineData.map(d => ({ 
      time: (new Date(d.t).getTime() / 1000) as Time, 
      value: d.v 
    }));
    const points = prepareChartData(rawPoints);
    
    baselineRef.current.setData(points);
  }, [baselineData]);

  // Build set of curve timestamps for marker snapping
  const curveTimestamps = useMemo(() => {
    return data.map(d => Math.floor(new Date(d.t).getTime() / 1000));
  }, [data]);

  // Snap marker time to nearest curve timestamp
  const snapToNearestTime = useMemo(() => {
    return (t: number): number => {
      if (curveTimestamps.length === 0) return t;
      let closest = curveTimestamps[0];
      let minDiff = Math.abs(t - closest);
      for (const ct of curveTimestamps) {
        const diff = Math.abs(t - ct);
        if (diff < minDiff) {
          minDiff = diff;
          closest = ct;
        }
      }
      return closest;
    };
  }, [curveTimestamps]);

  // Add buy/sell markers and window boundaries
  useEffect(() => {
    if (!seriesRef.current || !data.length) return;
    
    let rawMarkerData: any[] = [];

    // Add trade markers
    if (markers?.length) {
      rawMarkerData = [...rawMarkerData, ...markers.map(mk => {
        const markerTime = Math.floor(new Date(mk.time.slice(0, 19)).getTime() / 1000);
        const snappedTime = snapToNearestTime(markerTime);
        return {
          time: snappedTime as Time,
          position: mk.side === "BUY" ? ("belowBar" as const) : ("aboveBar" as const),
          color: mk.side === "BUY" ? "#22c55e" : "#ef4444",
          shape: mk.side === "BUY" ? ("arrowUp" as const) : ("arrowDown" as const),
          text: mk.side === "BUY"
            ? "买"
            : `卖${mk.pnl != null ? (mk.pnl >= 0 ? ` +$${mk.pnl.toFixed(0)}` : ` -$${Math.abs(mk.pnl).toFixed(0)}`) : ""}`,
          size: 1,
        };
      })];
    }

    // Add window boundaries
    if (windowBoundaries?.length) {
      rawMarkerData = [...rawMarkerData, ...windowBoundaries.map(wb => {
        const markerTime = Math.floor(new Date(wb.time.slice(0, 19)).getTime() / 1000);
        const snappedTime = snapToNearestTime(markerTime);
        return {
          time: snappedTime as Time,
          position: "inBar" as const,
          color: wb.color || "#f59e0b",
          shape: "circle" as const,
          text: wb.label,
          size: 2,
        };
      })];
    }

    if (rawMarkerData.length === 0) {
      // Clear markers if none
      createSeriesMarkers(seriesRef.current, []);
      return;
    }
    
    // Dedupe and sort markers (keep last for same time)
    const markerData = prepareChartData(rawMarkerData);
    
    createSeriesMarkers(seriesRef.current, markerData);
  }, [markers, windowBoundaries, data, snapToNearestTime]);

  // Calculate return percentage for display
  const currentEquity = data.length > 0 ? data[data.length - 1].v : initialCapital;
  const returnPct = initialCapital > 0 
    ? ((currentEquity - initialCapital) / initialCapital * 100).toFixed(2)
    : "0.00";
  const isPositive = currentEquity >= initialCapital;

  return (
    <div className="relative">
      <div ref={containerRef} className="w-full" style={{ height: `${height}px` }} />
      
      {/* Legend */}
      {showLegend && !isEmpty && (
        <div className="absolute top-2 left-3 flex items-center gap-4 pointer-events-none">
          <div className="flex items-center gap-1.5">
            <div className="w-5 h-0.5 bg-indigo-500 rounded" />
            <span className="text-[10px] text-slate-400">策略权益</span>
          </div>
          {baselineData.length > 0 && (
            <div className="flex items-center gap-1.5">
              <div className="w-5 h-0.5 bg-slate-500 rounded border-dashed" style={{ borderBottom: "1px dashed #64748b", background: "none" }} />
              <span className="text-[10px] text-slate-400">买入持有</span>
            </div>
          )}
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-green-400">▲ 买入</span>
            <span className="text-[10px] text-red-400">▼ 卖出</span>
          </div>
        </div>
      )}
      
      {/* Current equity display */}
      {showLegend && !isEmpty && (
        <div className="absolute top-2 right-3 text-right pointer-events-none">
          <div className="text-[10px] text-slate-500">当前权益</div>
          <div className={`text-sm font-bold font-mono ${isPositive ? "text-green-400" : "text-red-400"}`}>
            ${currentEquity.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
          </div>
          <div className={`text-[10px] ${isPositive ? "text-green-400" : "text-red-400"}`}>
            {isPositive ? "+" : ""}{returnPct}%
          </div>
        </div>
      )}
      
      {/* Empty state */}
      {isEmpty && (
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="text-center text-slate-500">
            <div className="text-sm">暂无数据</div>
            <div className="text-[10px] text-slate-600 mt-1">开始回放后将显示资产曲线</div>
          </div>
        </div>
      )}
    </div>
  );
}

export default EquityCurveChart;
