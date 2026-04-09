"use client";

import { useEffect, useRef } from "react";
import {
  createChart,
  LineSeries,
  CandlestickSeries,
  HistogramSeries,
  createSeriesMarkers,
  IChartApi,
  ISeriesApi,
  Time,
} from "lightweight-charts";

// ─── Types ────────────────────────────────────────────────────────────────────
export interface KlineBar {
  time: string;    // ISO timestamp
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface IndicatorPoint {
  time: string;
  values: Record<string, number>;
}

export interface TradeMarker {
  time: string;
  price: number;
  side: "BUY" | "SELL";
  quantity: number;
  pnl: number | null;
}

interface KlineChartProps {
  klines: KlineBar[];
  indicators: Record<string, IndicatorPoint[]>;
  markers: TradeMarker[];
  strategyType: string;
  height?: number;
}

// ─── Helper: Convert ISO time to lightweight-charts Time ─────────────────────
function toChartTime(isoTime: string): Time {
  return (new Date(isoTime.slice(0, 19)).getTime() / 1000) as Time;
}

// ─── Helper: Dedupe and sort data by time ────────────────────────────────────
// lightweight-charts requires strictly ascending, unique time values
function dedupeAndSort<T extends { time: Time }>(data: T[]): T[] {
  if (data.length === 0) return data;
  
  // Use Map to dedupe (keeps last occurrence for each time)
  const map = new Map<Time, T>();
  for (const item of data) {
    map.set(item.time, item);
  }
  
  // Convert to array and sort by time ascending
  return Array.from(map.values()).sort(
    (a, b) => (a.time as number) - (b.time as number)
  );
}

// ─── Helper: Strict ascending filter ─────────────────────────────────────────
// Ensures strictly ascending time order by removing any items with time <= previous
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

// ─── Colors ───────────────────────────────────────────────────────────────────
const COLORS = {
  background: "#0f172a",
  grid: "#1e293b",
  text: "#94a3b8",
  border: "#334155",
  upCandle: "#22c55e",
  downCandle: "#ef4444",
  maShort: "#eab308",
  maLong: "#a855f7",
  bollUpper: "#38bdf8",
  bollMiddle: "#e2e8f0",
  bollLower: "#38bdf8",
  rsi: "#f97316",
  macdLine: "#3b82f6",
  macdSignal: "#f97316",
  macdHistPos: "#22c55e",
  macdHistNeg: "#ef4444",
  buyMarker: "#22c55e",
  sellMarker: "#ef4444",
  // EMA Triple
  emaFast: "#eab308",
  emaMid: "#3b82f6",
  emaSlow: "#a855f7",
  // ATR Trend
  atrStop: "#ef4444",
  atrHighest: "#22c55e",
  // Turtle
  turtleUpper: "#38bdf8",
  turtleLower: "#f97316",
  // Ichimoku
  ichiTenkan: "#ef4444",
  ichiKijun: "#3b82f6",
  ichiSpanA: "#22c55e",
  ichiSpanB: "#f97316",
};

// ─── KlineChart Component ─────────────────────────────────────────────────────
export default function KlineChart({
  klines,
  indicators,
  markers,
  strategyType,
  height = 400,
}: KlineChartProps) {
  const mainContainerRef = useRef<HTMLDivElement>(null);
  const rsiContainerRef = useRef<HTMLDivElement>(null);
  const macdContainerRef = useRef<HTMLDivElement>(null);

  const mainChartRef = useRef<IChartApi | null>(null);
  const rsiChartRef = useRef<IChartApi | null>(null);
  const macdChartRef = useRef<IChartApi | null>(null);

  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const maShortRef = useRef<ISeriesApi<"Line"> | null>(null);
  const maLongRef = useRef<ISeriesApi<"Line"> | null>(null);
  const bollUpperRef = useRef<ISeriesApi<"Line"> | null>(null);
  const bollMiddleRef = useRef<ISeriesApi<"Line"> | null>(null);
  const bollLowerRef = useRef<ISeriesApi<"Line"> | null>(null);
  const rsiSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const macdLineRef = useRef<ISeriesApi<"Line"> | null>(null);
  const macdSignalRef = useRef<ISeriesApi<"Line"> | null>(null);
  const macdHistRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  // EMA Triple refs
  const emaFastRef = useRef<ISeriesApi<"Line"> | null>(null);
  const emaMidRef = useRef<ISeriesApi<"Line"> | null>(null);
  const emaSlowRef = useRef<ISeriesApi<"Line"> | null>(null);
  // ATR Trend refs
  const atrStopRef = useRef<ISeriesApi<"Line"> | null>(null);
  const atrHighestRef = useRef<ISeriesApi<"Line"> | null>(null);
  // Turtle refs
  const turtleUpperRef = useRef<ISeriesApi<"Line"> | null>(null);
  const turtleLowerRef = useRef<ISeriesApi<"Line"> | null>(null);
  // Ichimoku refs
  const ichiTenkanRef = useRef<ISeriesApi<"Line"> | null>(null);
  const ichiKijunRef = useRef<ISeriesApi<"Line"> | null>(null);
  const ichiSpanARef = useRef<ISeriesApi<"Line"> | null>(null);
  const ichiSpanBRef = useRef<ISeriesApi<"Line"> | null>(null);

  const prevKlineCountRef = useRef(0);

  const showMA = strategyType.toLowerCase() === "ma";
  const showBOLL = strategyType.toLowerCase() === "boll";
  const showRSI = strategyType.toLowerCase() === "rsi";
  const showMACD = strategyType.toLowerCase() === "macd";
  const showEMA = strategyType.toLowerCase() === "ema_triple";
  const showATR = strategyType.toLowerCase() === "atr_trend";
  const showTURTLE = strategyType.toLowerCase() === "turtle";
  const showICHIMOKU = strategyType.toLowerCase() === "ichimoku";

  // ─── Initialize Charts ─────────────────────────────────────────────────────
  useEffect(() => {
    if (!mainContainerRef.current) return;

    // Main chart options
    const chartOptions = {
      layout: {
        background: { color: COLORS.background },
        textColor: COLORS.text,
      },
      grid: {
        vertLines: { color: COLORS.grid },
        horzLines: { color: COLORS.grid },
      },
      rightPriceScale: {
        borderColor: COLORS.border,
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
      timeScale: {
        borderColor: COLORS.border,
        timeVisible: true,
        secondsVisible: false,
      },
      crosshair: {
        mode: 1,
        vertLine: { color: "#6366f1", width: 1 as const, style: 2 },
        horzLine: { color: "#6366f1", width: 1 as const, style: 2 },
      },
      autoSize: true,
    };

    // Create main chart
    const mainChart = createChart(mainContainerRef.current, chartOptions);

    // Add candlestick series
    const candleSeries = mainChart.addSeries(CandlestickSeries, {
      upColor: COLORS.upCandle,
      downColor: COLORS.downCandle,
      borderUpColor: COLORS.upCandle,
      borderDownColor: COLORS.downCandle,
      wickUpColor: COLORS.upCandle,
      wickDownColor: COLORS.downCandle,
    });

    mainChartRef.current = mainChart;
    candleSeriesRef.current = candleSeries;

    // Add MA indicator lines if needed
    if (showMA) {
      const maShort = mainChart.addSeries(LineSeries, {
        color: COLORS.maShort,
        lineWidth: 1,
        priceLineVisible: false,
        title: "MA短",
      });
      const maLong = mainChart.addSeries(LineSeries, {
        color: COLORS.maLong,
        lineWidth: 1,
        priceLineVisible: false,
        title: "MA长",
      });
      maShortRef.current = maShort;
      maLongRef.current = maLong;
    }

    // Add BOLL indicator lines if needed
    if (showBOLL) {
      const bollUpper = mainChart.addSeries(LineSeries, {
        color: COLORS.bollUpper,
        lineWidth: 1,
        priceLineVisible: false,
        title: "BOLL上",
      });
      const bollMiddle = mainChart.addSeries(LineSeries, {
        color: COLORS.bollMiddle,
        lineWidth: 1,
        priceLineVisible: false,
        title: "BOLL中",
      });
      const bollLower = mainChart.addSeries(LineSeries, {
        color: COLORS.bollLower,
        lineWidth: 1,
        priceLineVisible: false,
        title: "BOLL下",
      });
      bollUpperRef.current = bollUpper;
      bollMiddleRef.current = bollMiddle;
      bollLowerRef.current = bollLower;
    }

    // Add EMA Triple indicator lines if needed
    if (showEMA) {
      const ef = mainChart.addSeries(LineSeries, { color: COLORS.emaFast, lineWidth: 1, priceLineVisible: false, title: "EMA快" });
      const em = mainChart.addSeries(LineSeries, { color: COLORS.emaMid, lineWidth: 1, priceLineVisible: false, title: "EMA中" });
      const es = mainChart.addSeries(LineSeries, { color: COLORS.emaSlow, lineWidth: 1, priceLineVisible: false, title: "EMA慢" });
      emaFastRef.current = ef;
      emaMidRef.current = em;
      emaSlowRef.current = es;
    }

    // Add ATR Trend indicator lines if needed
    if (showATR) {
      const stop = mainChart.addSeries(LineSeries, { color: COLORS.atrStop, lineWidth: 1, lineStyle: 2, priceLineVisible: false, title: "止损线" });
      const highest = mainChart.addSeries(LineSeries, { color: COLORS.atrHighest, lineWidth: 1, lineStyle: 2, priceLineVisible: false, title: "趋势线" });
      atrStopRef.current = stop;
      atrHighestRef.current = highest;
    }

    // Add Turtle indicator lines if needed
    if (showTURTLE) {
      const upper = mainChart.addSeries(LineSeries, { color: COLORS.turtleUpper, lineWidth: 1, priceLineVisible: false, title: "入场上轨" });
      const lower = mainChart.addSeries(LineSeries, { color: COLORS.turtleLower, lineWidth: 1, priceLineVisible: false, title: "出场下轨" });
      turtleUpperRef.current = upper;
      turtleLowerRef.current = lower;
    }

    // Add Ichimoku indicator lines if needed
    if (showICHIMOKU) {
      const tenkan = mainChart.addSeries(LineSeries, { color: COLORS.ichiTenkan, lineWidth: 1, priceLineVisible: false, title: "转折线" });
      const kijun = mainChart.addSeries(LineSeries, { color: COLORS.ichiKijun, lineWidth: 1, priceLineVisible: false, title: "基准线" });
      const spanA = mainChart.addSeries(LineSeries, { color: COLORS.ichiSpanA, lineWidth: 1, lineStyle: 2, priceLineVisible: false, title: "先行A" });
      const spanB = mainChart.addSeries(LineSeries, { color: COLORS.ichiSpanB, lineWidth: 1, lineStyle: 2, priceLineVisible: false, title: "先行B" });
      ichiTenkanRef.current = tenkan;
      ichiKijunRef.current = kijun;
      ichiSpanARef.current = spanA;
      ichiSpanBRef.current = spanB;
    }

    // Create RSI sub-chart if needed
    if (showRSI && rsiContainerRef.current) {
      const rsiChart = createChart(rsiContainerRef.current, {
        ...chartOptions,
        rightPriceScale: {
          ...chartOptions.rightPriceScale,
          scaleMargins: { top: 0.1, bottom: 0.1 },
        },
      });

      const rsiSeries = rsiChart.addSeries(LineSeries, {
        color: COLORS.rsi,
        lineWidth: 1,
        priceLineVisible: false,
        title: "RSI",
      });

      // Add RSI reference lines at 30 and 70
      rsiSeries.createPriceLine({
        price: 70,
        color: "#475569",
        lineWidth: 1,
        lineStyle: 2,
        axisLabelVisible: true,
        title: "超买",
      });
      rsiSeries.createPriceLine({
        price: 30,
        color: "#475569",
        lineWidth: 1,
        lineStyle: 2,
        axisLabelVisible: true,
        title: "超卖",
      });

      rsiChartRef.current = rsiChart;
      rsiSeriesRef.current = rsiSeries;

      // Sync RSI time scale with main chart
      mainChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
        if (range) rsiChart.timeScale().setVisibleLogicalRange(range);
      });
    }

    // Create MACD sub-chart if needed
    if (showMACD && macdContainerRef.current) {
      const macdChart = createChart(macdContainerRef.current, {
        ...chartOptions,
        rightPriceScale: {
          ...chartOptions.rightPriceScale,
          scaleMargins: { top: 0.1, bottom: 0.1 },
        },
      });

      const macdLine = macdChart.addSeries(LineSeries, {
        color: COLORS.macdLine,
        lineWidth: 1,
        priceLineVisible: false,
        title: "MACD",
      });
      const macdSignal = macdChart.addSeries(LineSeries, {
        color: COLORS.macdSignal,
        lineWidth: 1,
        priceLineVisible: false,
        title: "Signal",
      });
      const macdHist = macdChart.addSeries(HistogramSeries, {
        color: COLORS.macdHistPos,
        priceLineVisible: false,
        title: "Histogram",
      });

      macdChartRef.current = macdChart;
      macdLineRef.current = macdLine;
      macdSignalRef.current = macdSignal;
      macdHistRef.current = macdHist;

      // Sync MACD time scale with main chart
      mainChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
        if (range) macdChart.timeScale().setVisibleLogicalRange(range);
      });
    }

    // Cleanup
    return () => {
      // Remove main chart with error handling
      try {
        if (mainChartRef.current && mainContainerRef.current && document.body.contains(mainContainerRef.current)) {
          mainChartRef.current.remove();
        }
      } catch (e) {
        console.warn("Main chart removal error:", e);
      }

      // Remove RSI chart with error handling
      try {
        if (rsiChartRef.current && rsiContainerRef.current && document.body.contains(rsiContainerRef.current)) {
          rsiChartRef.current.remove();
        }
      } catch (e) {
        console.warn("RSI chart removal error:", e);
      }

      // Remove MACD chart with error handling
      try {
        if (macdChartRef.current && macdContainerRef.current && document.body.contains(macdContainerRef.current)) {
          macdChartRef.current.remove();
        }
      } catch (e) {
        console.warn("MACD chart removal error:", e);
      }

      // Clear all refs
      mainChartRef.current = null;
      rsiChartRef.current = null;
      macdChartRef.current = null;
      candleSeriesRef.current = null;
      maShortRef.current = null;
      maLongRef.current = null;
      bollUpperRef.current = null;
      bollMiddleRef.current = null;
      bollLowerRef.current = null;
      emaFastRef.current = null;
      emaMidRef.current = null;
      emaSlowRef.current = null;
      atrStopRef.current = null;
      atrHighestRef.current = null;
      turtleUpperRef.current = null;
      turtleLowerRef.current = null;
      ichiTenkanRef.current = null;
      ichiKijunRef.current = null;
      ichiSpanARef.current = null;
      ichiSpanBRef.current = null;
      rsiSeriesRef.current = null;
      macdLineRef.current = null;
      macdSignalRef.current = null;
      macdHistRef.current = null;
    };
  }, [showMA, showBOLL, showRSI, showMACD, showEMA, showATR, showTURTLE, showICHIMOKU]);

  // ─── Update Kline Data ─────────────────────────────────────────────────────
  useEffect(() => {
    if (!candleSeriesRef.current || !mainChartRef.current || !klines.length) return;

    const rawCandleData = klines.map((bar) => ({
      time: toChartTime(bar.time),
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
    }));
    
    // Dedupe and sort to ensure strictly ascending unique times
    const candleData = prepareChartData(rawCandleData);

    // Smart update: if klines increased, update only new ones
    // But we need to check time to avoid duplicate/out-of-order updates
    if (candleData.length > prevKlineCountRef.current && prevKlineCountRef.current > 0) {
      const existingCount = prevKlineCountRef.current;
      const newData = candleData.slice(existingCount);
      
      // Only update if new data has times after the last known data
      // This prevents assertion errors from out-of-order updates
      newData.forEach((bar) => {
        candleSeriesRef.current?.update(bar);
      });
    } else {
      candleSeriesRef.current.setData(candleData);
      mainChartRef.current.timeScale().fitContent();
    }

    prevKlineCountRef.current = candleData.length;
  }, [klines]);

  // ─── Update MA Indicators ──────────────────────────────────────────────────
  useEffect(() => {
    if (!showMA || !indicators.ma) return;

    const maData = indicators.ma;

    if (maShortRef.current) {
      const rawShortData = maData
        .filter((p) => p.values.ma_short != null)
        .map((p) => ({ time: toChartTime(p.time), value: p.values.ma_short }));
      maShortRef.current.setData(prepareChartData(rawShortData));
    }

    if (maLongRef.current) {
      const rawLongData = maData
        .filter((p) => p.values.ma_long != null)
        .map((p) => ({ time: toChartTime(p.time), value: p.values.ma_long }));
      maLongRef.current.setData(prepareChartData(rawLongData));
    }
  }, [indicators, showMA]);

  // ─── Update BOLL Indicators ────────────────────────────────────────────────
  useEffect(() => {
    if (!showBOLL || !indicators.boll) return;

    const bollData = indicators.boll;

    if (bollUpperRef.current) {
      const rawUpperData = bollData
        .filter((p) => p.values.upper != null)
        .map((p) => ({ time: toChartTime(p.time), value: p.values.upper }));
      bollUpperRef.current.setData(prepareChartData(rawUpperData));
    }

    if (bollMiddleRef.current) {
      const rawMiddleData = bollData
        .filter((p) => p.values.middle != null)
        .map((p) => ({ time: toChartTime(p.time), value: p.values.middle }));
      bollMiddleRef.current.setData(prepareChartData(rawMiddleData));
    }

    if (bollLowerRef.current) {
      const rawLowerData = bollData
        .filter((p) => p.values.lower != null)
        .map((p) => ({ time: toChartTime(p.time), value: p.values.lower }));
      bollLowerRef.current.setData(prepareChartData(rawLowerData));
    }
  }, [indicators, showBOLL]);

  // ─── Update RSI Indicator ──────────────────────────────────────────────────
  useEffect(() => {
    if (!showRSI || !rsiSeriesRef.current || !indicators.rsi) return;

    const rawRsiData = indicators.rsi
      .filter((p) => p.values.rsi != null)
      .map((p) => ({ time: toChartTime(p.time), value: p.values.rsi }));

    rsiSeriesRef.current.setData(prepareChartData(rawRsiData));
    rsiChartRef.current?.timeScale().fitContent();
  }, [indicators, showRSI]);

  // ─── Update MACD Indicator ─────────────────────────────────────────────────
  useEffect(() => {
    if (!showMACD || !indicators.macd) return;

    const macdData = indicators.macd;

    if (macdLineRef.current) {
      const rawLineData = macdData
        .filter((p) => p.values.macd != null)
        .map((p) => ({ time: toChartTime(p.time), value: p.values.macd }));
      macdLineRef.current.setData(prepareChartData(rawLineData));
    }

    if (macdSignalRef.current) {
      const rawSignalData = macdData
        .filter((p) => p.values.signal != null)
        .map((p) => ({ time: toChartTime(p.time), value: p.values.signal }));
      macdSignalRef.current.setData(prepareChartData(rawSignalData));
    }

    if (macdHistRef.current) {
      const rawHistData = macdData
        .filter((p) => p.values.histogram != null)
        .map((p) => ({
          time: toChartTime(p.time),
          value: p.values.histogram,
          color: p.values.histogram >= 0 ? COLORS.macdHistPos : COLORS.macdHistNeg,
        }));
      macdHistRef.current.setData(prepareChartData(rawHistData));
    }

    macdChartRef.current?.timeScale().fitContent();
  }, [indicators, showMACD]);

  // ─── Update EMA Triple Indicators ───────────────────────────────────────────
  useEffect(() => {
    if (!showEMA || !indicators.ema) return;

    const emaData = indicators.ema;

    if (emaFastRef.current) {
      const raw = emaData
        .filter((p) => p.values.ema_fast != null)
        .map((p) => ({ time: toChartTime(p.time), value: p.values.ema_fast }));
      emaFastRef.current.setData(prepareChartData(raw));
    }

    if (emaMidRef.current) {
      const raw = emaData
        .filter((p) => p.values.ema_mid != null)
        .map((p) => ({ time: toChartTime(p.time), value: p.values.ema_mid }));
      emaMidRef.current.setData(prepareChartData(raw));
    }

    if (emaSlowRef.current) {
      const raw = emaData
        .filter((p) => p.values.ema_slow != null)
        .map((p) => ({ time: toChartTime(p.time), value: p.values.ema_slow }));
      emaSlowRef.current.setData(prepareChartData(raw));
    }
  }, [indicators, showEMA]);

  // ─── Update ATR Trend Indicators ────────────────────────────────────────────
  useEffect(() => {
    if (!showATR || !indicators.atr) return;

    const atrData = indicators.atr;

    if (atrStopRef.current) {
      const raw = atrData
        .filter((p) => p.values.chandelier_stop != null)
        .map((p) => ({ time: toChartTime(p.time), value: p.values.chandelier_stop }));
      atrStopRef.current.setData(prepareChartData(raw));
    }

    if (atrHighestRef.current) {
      const raw = atrData
        .filter((p) => p.values.highest != null)
        .map((p) => ({ time: toChartTime(p.time), value: p.values.highest }));
      atrHighestRef.current.setData(prepareChartData(raw));
    }
  }, [indicators, showATR]);

  // ─── Update Turtle Indicators ───────────────────────────────────────────────
  useEffect(() => {
    if (!showTURTLE || !indicators.turtle) return;

    const turtleData = indicators.turtle;

    if (turtleUpperRef.current) {
      const raw = turtleData
        .filter((p) => p.values.upper != null)
        .map((p) => ({ time: toChartTime(p.time), value: p.values.upper }));
      turtleUpperRef.current.setData(prepareChartData(raw));
    }

    if (turtleLowerRef.current) {
      const raw = turtleData
        .filter((p) => p.values.lower != null)
        .map((p) => ({ time: toChartTime(p.time), value: p.values.lower }));
      turtleLowerRef.current.setData(prepareChartData(raw));
    }
  }, [indicators, showTURTLE]);

  // ─── Update Ichimoku Indicators ─────────────────────────────────────────────
  useEffect(() => {
    if (!showICHIMOKU || !indicators.ichimoku) return;

    const ichiData = indicators.ichimoku;

    if (ichiTenkanRef.current) {
      const raw = ichiData
        .filter((p) => p.values.tenkan != null)
        .map((p) => ({ time: toChartTime(p.time), value: p.values.tenkan }));
      ichiTenkanRef.current.setData(prepareChartData(raw));
    }

    if (ichiKijunRef.current) {
      const raw = ichiData
        .filter((p) => p.values.kijun != null)
        .map((p) => ({ time: toChartTime(p.time), value: p.values.kijun }));
      ichiKijunRef.current.setData(prepareChartData(raw));
    }

    if (ichiSpanARef.current) {
      const raw = ichiData
        .filter((p) => p.values.span_a != null)
        .map((p) => ({ time: toChartTime(p.time), value: p.values.span_a }));
      ichiSpanARef.current.setData(prepareChartData(raw));
    }

    if (ichiSpanBRef.current) {
      const raw = ichiData
        .filter((p) => p.values.span_b != null)
        .map((p) => ({ time: toChartTime(p.time), value: p.values.span_b }));
      ichiSpanBRef.current.setData(prepareChartData(raw));
    }
  }, [indicators, showICHIMOKU]);

  // ─── Update Trade Markers ──────────────────────────────────────────────────
  useEffect(() => {
    if (!candleSeriesRef.current || !markers?.length || !klines.length) return;

    const rawMarkerData = markers.map((mk) => ({
      time: toChartTime(mk.time),
      position: mk.side === "BUY" ? ("belowBar" as const) : ("aboveBar" as const),
      color: mk.side === "BUY" ? COLORS.buyMarker : COLORS.sellMarker,
      shape: mk.side === "BUY" ? ("arrowUp" as const) : ("arrowDown" as const),
      text:
        mk.side === "BUY"
          ? "买"
          : `卖${mk.pnl != null ? (mk.pnl >= 0 ? ` +$${mk.pnl.toFixed(0)}` : ` -$${Math.abs(mk.pnl).toFixed(0)}`) : ""}`,
      size: 1,
    }));
    
    // Dedupe and sort markers
    const markerData = prepareChartData(rawMarkerData);

    createSeriesMarkers(candleSeriesRef.current, markerData);
  }, [markers, klines]);

  // ─── Build Legend Items ────────────────────────────────────────────────────
  const legendItems: { color: string; label: string; dashed?: boolean }[] = [];
  if (showMA) {
    legendItems.push({ color: COLORS.maShort, label: "MA短期" });
    legendItems.push({ color: COLORS.maLong, label: "MA长期" });
  }
  if (showBOLL) {
    legendItems.push({ color: COLORS.bollUpper, label: "BOLL上轨" });
    legendItems.push({ color: COLORS.bollMiddle, label: "BOLL中轨" });
    legendItems.push({ color: COLORS.bollLower, label: "BOLL下轨" });
  }
  if (showEMA) {
    legendItems.push({ color: COLORS.emaFast, label: "EMA快" });
    legendItems.push({ color: COLORS.emaMid, label: "EMA中" });
    legendItems.push({ color: COLORS.emaSlow, label: "EMA慢" });
  }
  if (showATR) {
    legendItems.push({ color: COLORS.atrStop, label: "止损线", dashed: true });
    legendItems.push({ color: COLORS.atrHighest, label: "趋势线", dashed: true });
  }
  if (showTURTLE) {
    legendItems.push({ color: COLORS.turtleUpper, label: "入场上轨" });
    legendItems.push({ color: COLORS.turtleLower, label: "出场下轨" });
  }
  if (showICHIMOKU) {
    legendItems.push({ color: COLORS.ichiTenkan, label: "转折线" });
    legendItems.push({ color: COLORS.ichiKijun, label: "基准线" });
    legendItems.push({ color: COLORS.ichiSpanA, label: "先行A", dashed: true });
    legendItems.push({ color: COLORS.ichiSpanB, label: "先行B", dashed: true });
  }

  return (
    <div className="relative flex flex-col gap-1">
      {/* Legend */}
      <div className="absolute top-2 left-3 z-10 flex items-center gap-3 pointer-events-none">
        <div className="flex items-center gap-1.5">
          <div className="w-3 h-3 rounded-sm" style={{ backgroundColor: COLORS.upCandle }} />
          <span className="text-[10px] text-slate-400">涨</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-3 h-3 rounded-sm" style={{ backgroundColor: COLORS.downCandle }} />
          <span className="text-[10px] text-slate-400">跌</span>
        </div>
        {legendItems.map((item) => (
          <div key={item.label} className="flex items-center gap-1.5">
            <div
              className="w-4 h-0.5 rounded"
              style={{
                backgroundColor: item.dashed ? "transparent" : item.color,
                borderBottom: item.dashed ? `1px dashed ${item.color}` : "none",
              }}
            />
            <span className="text-[10px] text-slate-400">{item.label}</span>
          </div>
        ))}
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-green-400">▲ 买入</span>
          <span className="text-[10px] text-red-400">▼ 卖出</span>
        </div>
      </div>

      {/* Main Chart (Candlestick + MA/BOLL) */}
      <div
        ref={mainContainerRef}
        className="w-full"
        style={{ height: `${height}px`, backgroundColor: COLORS.background }}
      />

      {/* RSI Sub-chart */}
      {showRSI && (
        <div className="relative">
          <div className="absolute top-1 left-3 z-10 pointer-events-none">
            <span className="text-[10px] text-orange-400">RSI</span>
          </div>
          <div
            ref={rsiContainerRef}
            className="w-full"
            style={{ height: "120px", backgroundColor: COLORS.background }}
          />
        </div>
      )}

      {/* MACD Sub-chart */}
      {showMACD && (
        <div className="relative">
          <div className="absolute top-1 left-3 z-10 flex items-center gap-2 pointer-events-none">
            <span className="text-[10px] text-blue-400">MACD</span>
            <span className="text-[10px] text-orange-400">Signal</span>
            <span className="text-[10px] text-slate-400">Hist</span>
          </div>
          <div
            ref={macdContainerRef}
            className="w-full"
            style={{ height: "120px", backgroundColor: COLORS.background }}
          />
        </div>
      )}

      {/* Empty State */}
      {klines.length === 0 && (
        <div className="absolute inset-0 flex items-center justify-center bg-slate-900/80">
          <div className="text-center text-slate-500">
            <div className="text-sm">暂无K线数据</div>
            <div className="text-[10px] text-slate-600 mt-1">开始回放后将显示K线图</div>
          </div>
        </div>
      )}
    </div>
  );
}
