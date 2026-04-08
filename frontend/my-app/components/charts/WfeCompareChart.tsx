"use client";

import React from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Cell
} from "recharts";

interface WindowData {
  window_index: number;
  wfe: number;
  train_return?: number;
  test_return?: number;
  [key: string]: any;
}

interface WfeCompareChartProps {
  data: WindowData[];
  height?: number;
}

const CustomTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    const val = payload[0].value;
    const isGood = val >= 50; // Typically WFE > 50% is considered good
    return (
      <div className="bg-slate-800 border border-slate-700 p-3 rounded-lg shadow-xl">
        <p className="text-slate-300 text-sm mb-1">{label}</p>
        <p className={`text-base font-bold font-mono ${isGood ? "text-green-400" : "text-amber-400"}`}>
          WFE: {val.toFixed(2)}%
        </p>
        <p className="text-xs text-slate-500 mt-1">
          {isGood ? "参数在此窗口具有较好的一致性" : "此窗口存在过拟合风险"}
        </p>
      </div>
    );
  }
  return null;
};

export function WfeCompareChart({ data, height = 300 }: WfeCompareChartProps) {
  if (!data || data.length === 0) {
    return (
      <div className="flex items-center justify-center text-slate-500" style={{ height }}>
        暂无 WFE 数据
      </div>
    );
  }

  const chartData = data.map(w => ({
    name: `窗口 ${w.window_index}`,
    wfe: w.wfe * 100, // Convert to percentage
    rawWfe: w.wfe,
  }));

  return (
    <div style={{ height, width: "100%" }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={chartData} margin={{ top: 20, right: 20, left: -20, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
          <XAxis 
            dataKey="name" 
            stroke="#64748b" 
            tick={{ fill: "#64748b", fontSize: 12 }}
            axisLine={{ stroke: "#334155" }}
            tickLine={false}
          />
          <YAxis 
            stroke="#64748b" 
            tick={{ fill: "#64748b", fontSize: 12 }}
            axisLine={false}
            tickLine={false}
            tickFormatter={(val) => `${val}%`}
          />
          <Tooltip content={<CustomTooltip />} cursor={{ fill: "#1e293b", opacity: 0.4 }} />
          <ReferenceLine y={50} stroke="#f59e0b" strokeDasharray="3 3" />
          <ReferenceLine y={100} stroke="#22c55e" strokeDasharray="3 3" />
          <Bar dataKey="wfe" radius={[4, 4, 0, 0]} maxBarSize={40}>
            {chartData.map((entry, index) => (
              <Cell 
                key={`cell-${index}`} 
                fill={entry.rawWfe >= 1 ? "#22c55e" : entry.rawWfe >= 0.5 ? "#3b82f6" : "#f59e0b"} 
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
