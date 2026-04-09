"use client";

interface DataSourceBadgeProps {
  source: "REAL" | "PAPER" | "BACKTEST" | "REPLAY" | "MOCK";
  className?: string;
}

const badgeConfig = {
  REAL: {
    label: "实盘",
    className: "bg-emerald-100 text-emerald-800 border-emerald-300",
  },
  PAPER: {
    label: "模拟盘",
    className: "bg-blue-100 text-blue-800 border-blue-300",
  },
  BACKTEST: {
    label: "回测 (上帝视角)",
    className: "bg-purple-100 text-purple-800 border-purple-300",
  },
  REPLAY: {
    label: "回放 (盲人视角)",
    className: "bg-orange-100 text-orange-800 border-orange-300",
  },
  MOCK: {
    label: "演示数据",
    className: "bg-yellow-100 text-yellow-800 border-yellow-300",
  },
};

export function DataSourceBadge({ source, className = "" }: DataSourceBadgeProps) {
  const config = badgeConfig[source] || badgeConfig.MOCK;

  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border ${config.className} ${className}`}
    >
      {config.label}
    </span>
  );
}
