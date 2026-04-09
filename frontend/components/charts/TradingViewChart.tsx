"use client";

import { useEffect, useRef, useState } from "react";
import { createChart, CandlestickSeries, IChartApi, ISeriesApi, CandlestickData, Time } from "lightweight-charts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface TradingViewChartProps {
  symbol?: string;
  interval?: string;
}

interface KlineItem {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
}

export function TradingViewChart({ symbol = "BTCUSDT", interval = "1h" }: TradingViewChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candlestickSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  const createFallbackCandleData = (): CandlestickData<Time>[] => {
    const now = Math.floor(Date.now() / 1000);
    let lastClose = 50000;
    const data: CandlestickData<Time>[] = [];

    for (let i = 199; i >= 0; i--) {
      const time = now - i * 3600;
      const drift = (Math.random() - 0.5) * 1200;
      const open = lastClose;
      const close = Math.max(1000, open + drift);
      const high = Math.max(open, close) + Math.random() * 300;
      const low = Math.min(open, close) - Math.random() * 300;
      data.push({
        time: time as Time,
        open,
        high,
        low,
        close,
      });
      lastClose = close;
    }

    return data;
  };

  // Reset chart data when symbol changes
  useEffect(() => {
    if (candlestickSeriesRef.current) {
      candlestickSeriesRef.current.setData([]);
    }
  }, [symbol]);

  useEffect(() => {
    if (!chartContainerRef.current) return;

    // Save the container ref locally to ensure we use the exact same node for cleanup
    const container = chartContainerRef.current;

    // Create chart
    const chart = createChart(container, {
      layout: {
        background: { color: "#0f172a" },
        textColor: "#e2e8f0",
      },
      grid: {
        vertLines: { color: "#1e293b" },
        horzLines: { color: "#1e293b" },
      },
      crosshair: {
        mode: 1,
      },
      rightPriceScale: {
        borderColor: "#334155",
      },
      timeScale: {
        borderColor: "#334155",
        timeVisible: true,
      },
      autoSize: false,
    });

    // Create candlestick series (lightweight-charts v5 API)
    const candlestickSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderUpColor: "#22c55e",
      borderDownColor: "#ef4444",
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444",
    });

    // Store references
    chartRef.current = chart;
    candlestickSeriesRef.current = candlestickSeries;

    // Handle resize
    const handleResize = () => {
      if (chartContainerRef.current && chartRef.current && document.body.contains(chartContainerRef.current)) {
        chart.applyOptions({
          width: chartContainerRef.current.clientWidth,
          height: chartContainerRef.current.clientHeight,
        });
      }
    };

    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      if (chart) {
        try {
          chart.remove();
        } catch (e) {
          // Ignore DOM removal errors from lightweight-charts
          console.warn("Chart removal error:", e);
        }
      }
      try {
        chartRef.current = null;
        candlestickSeriesRef.current = null;
      } catch (e) {
        // Ignore cleanup errors
      }
    };
  }, []);

  // Update data when symbol or interval changes
  useEffect(() => {
    if (!candlestickSeriesRef.current || !chartRef.current) return;
    
    const fetchData = async () => {
      setIsLoading(true);
      setErrorMessage("");
      try {
        const response = await fetch(`/api/v1/market/klines/${symbol}?interval=${interval}&limit=200`);
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        const result = (await response.json()) as { data: KlineItem[] };
        
        if (!chartRef.current || !candlestickSeriesRef.current) return;
        
        const candleData: CandlestickData<Time>[] = result.data.map((item) => ({
          time: (new Date(item.timestamp).getTime() / 1000) as Time,
          open: item.open,
          high: item.high,
          low: item.low,
          close: item.close,
        }));
        
        candleData.sort((a, b) => (a.time as number) - (b.time as number));
        
        candlestickSeriesRef.current?.setData(candleData);
        chartRef.current?.timeScale().fitContent();
      } catch {
        if (chartRef.current && candlestickSeriesRef.current) {
          const fallbackData = createFallbackCandleData();
          candlestickSeriesRef.current.setData(fallbackData);
          chartRef.current.timeScale().fitContent();
          setErrorMessage("实时行情暂不可用，已切换为本地演示数据");
        }
      } finally {
        setIsLoading(false);
      }
    };

    fetchData();
  }, [symbol, interval]);

  return (
    <Card className="w-full h-full bg-slate-900 border-slate-800">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-slate-100 flex items-center gap-2">
            <span className="text-xl font-bold">{symbol}</span>
            <span className="text-sm font-normal text-slate-400">永续合约</span>
          </CardTitle>
          <div className="flex items-center gap-2" />
        </div>
        {errorMessage && <div className="text-xs text-amber-300 mt-2">{errorMessage}</div>}
      </CardHeader>
      <CardContent className="p-0">
        <div className="relative">
          {isLoading && (
            <div className="absolute inset-0 flex items-center justify-center bg-slate-900/50 z-10">
              <div className="text-slate-400">加载中...</div>
            </div>
          )}
          <div
            ref={chartContainerRef}
            className="w-full h-[500px]"
          />
        </div>
      </CardContent>
    </Card>
  );
}
