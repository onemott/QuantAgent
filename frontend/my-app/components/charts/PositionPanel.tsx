"use client";

import { PackageOpen } from "lucide-react";

// ─── Types ────────────────────────────────────────────────────────────────────
export interface PositionInfo {
  has_position: boolean;
  side: string;         // "LONG" | "SHORT" | ""
  quantity: number;
  avg_price: number;
  current_price: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
}

export interface PositionPanelProps {
  position: PositionInfo | null;
}

// ─── Utilities ────────────────────────────────────────────────────────────────
function formatPrice(price: number): string {
  if (price >= 1000) {
    return price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  } else if (price >= 1) {
    return price.toFixed(4);
  } else {
    return price.toFixed(6);
  }
}

function formatQuantity(quantity: number): string {
  if (quantity >= 1) {
    return quantity.toFixed(4);
  } else {
    return quantity.toFixed(6);
  }
}

function formatPnl(pnl: number): string {
  const sign = pnl >= 0 ? "+" : "";
  return `${sign}${pnl.toFixed(2)}`;
}

function formatPnlPct(pct: number): string {
  const sign = pct >= 0 ? "+" : "";
  return `${sign}${pct.toFixed(2)}%`;
}

// ─── Component ────────────────────────────────────────────────────────────────
export default function PositionPanel({ position }: PositionPanelProps) {
  // 加载中或数据为 null
  if (position === null || position === undefined) {
    return (
      <div className="bg-slate-900/50 border border-slate-700 rounded-xl overflow-hidden">
        {/* 标题栏 */}
        <div className="bg-slate-800 px-4 py-3 border-b border-slate-700">
          <h3 className="text-sm font-medium text-slate-200">当前持仓</h3>
        </div>
        {/* 加载占位符 */}
        <div className="p-4">
          <div className="grid grid-cols-2 gap-4">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="space-y-2">
                <div className="h-3 w-16 bg-slate-700 rounded animate-pulse" />
                <div className="h-5 w-24 bg-slate-800 rounded animate-pulse" />
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  // 空仓状态
  if (!position.has_position) {
    return (
      <div className="bg-slate-900/50 border border-slate-700 rounded-xl overflow-hidden">
        {/* 标题栏 */}
        <div className="bg-slate-800 px-4 py-3 border-b border-slate-700">
          <h3 className="text-sm font-medium text-slate-200">当前持仓</h3>
        </div>
        {/* 空仓提示 */}
        <div className="flex flex-col items-center justify-center py-10 text-slate-500">
          <PackageOpen className="w-10 h-10 mb-3 opacity-40" />
          <span className="text-sm">当前无持仓</span>
        </div>
      </div>
    );
  }

  // 有持仓状态
  const isLong = position.side === "LONG";
  const isProfitable = position.unrealized_pnl >= 0;

  return (
    <div className="bg-slate-900/50 border border-slate-700 rounded-xl overflow-hidden">
      {/* 标题栏 */}
      <div className="bg-slate-800 px-4 py-3 border-b border-slate-700 flex items-center justify-between">
        <h3 className="text-sm font-medium text-slate-200">当前持仓</h3>
        <span
          className={`
            px-2 py-0.5 text-xs font-medium rounded-full
            ${isLong 
              ? "bg-green-500/10 text-green-400 border border-green-500/20" 
              : "bg-red-500/10 text-red-400 border border-red-500/20"
            }
          `}
        >
          {isLong ? "多头" : "空头"}
        </span>
      </div>

      {/* 持仓信息网格 */}
      <div className="p-4">
        <div className="grid grid-cols-2 gap-4">
          {/* 持仓数量 */}
          <div>
            <p className="text-xs text-slate-400 mb-1">持仓数量</p>
            <p className="text-sm font-medium text-slate-100">
              {formatQuantity(position.quantity)}
            </p>
          </div>

          {/* 持仓均价 */}
          <div>
            <p className="text-xs text-slate-400 mb-1">持仓均价</p>
            <p className="text-sm font-medium text-slate-100">
              ${formatPrice(position.avg_price)}
            </p>
          </div>

          {/* 当前市价 */}
          <div>
            <p className="text-xs text-slate-400 mb-1">当前市价</p>
            <p className="text-sm font-medium text-slate-100">
              ${formatPrice(position.current_price)}
            </p>
          </div>

          {/* 未实现盈亏 */}
          <div>
            <p className="text-xs text-slate-400 mb-1">未实现盈亏</p>
            <div className="flex items-baseline gap-1.5">
              <p className={`text-sm font-bold ${isProfitable ? "text-green-400" : "text-red-400"}`}>
                ${formatPnl(position.unrealized_pnl)}
              </p>
              <p className={`text-xs ${isProfitable ? "text-green-400/70" : "text-red-400/70"}`}>
                ({formatPnlPct(position.unrealized_pnl_pct)})
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
