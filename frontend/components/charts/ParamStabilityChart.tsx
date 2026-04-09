"use client";

import React, { useMemo } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend
} from "recharts";

interface WindowData {
  window_index: number;
  best_params?: Record<string, number>;
  [key: string]: any;
}

interface ParamStabilityChartProps {
  data: WindowData[];
  height?: number;
}

const COLORS = ["#3b82f6", "#10b981", "#f59e0b", "#ec4899", "#8b5cf6", "#14b8a6", "#f43f5e"];

const CustomTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    return (
      <div className="bg-slate-800 border border-slate-700 p-3 rounded-lg shadow-xl">
        <p className="text-slate-300 text-sm mb-2">{label}</p>
        {payload.map((p: any, i: number) => (
          <div key={i} className="flex items-center justify-between gap-4 mb-1">
            <div className="flex items-center gap-1.5">
              <div className="w-2 h-2 rounded-full" style={{ backgroundColor: p.color }} />
              <span className="text-xs text-slate-400">{p.name}</span>
            </div>
            <span className="text-sm font-bold font-mono text-slate-200">
              {p.value}
            </span>
          </div>
        ))}
      </div>
    );
  }
  return null;
};

export function ParamStabilityChart({ data, height = 300 }: ParamStabilityChartProps) {
  const chartData = useMemo(() => {
    if (!data || data.length === 0) return [];
    
    return data.map(w => {
      const point: any = { name: `W${w.window_index}` };
      if (w.best_params) {
        Object.keys(w.best_params).forEach(k => {
          point[k] = w.best_params![k];
        });
      }
      return point;
    });
  }, [data]);

  const paramKeys = useMemo(() => {
    if (!data || data.length === 0) return [];
    const keys = new Set<string>();
    data.forEach(w => {
      if (w.best_params) {
        Object.keys(w.best_params).forEach(k => keys.add(k));
      }
    });
    return Array.from(keys);
  }, [data]);

  if (!data || data.length === 0 || paramKeys.length === 0) {
    return (
      <div className="flex items-center justify-center text-slate-500" style={{ height }}>
        暂无参数演变数据
      </div>
    );
  }

  return (
    <div style={{ height, width: "100%" }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={chartData} margin={{ top: 20, right: 20, left: -20, bottom: 0 }}>
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
            domain={['auto', 'auto']}
          />
          <Tooltip content={<CustomTooltip />} />
          <Legend wrapperStyle={{ fontSize: '12px', color: '#94a3b8' }} />
          
          {paramKeys.map((key, index) => (
            <Line
              key={key}
              type="stepAfter"
              dataKey={key}
              name={key}
              stroke={COLORS[index % COLORS.length]}
              strokeWidth={2}
              dot={{ r: 4, strokeWidth: 2, fill: '#0f172a' }}
              activeDot={{ r: 6, strokeWidth: 0 }}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
