"use client";

import { useEffect, useRef } from "react";

// ─── Types ────────────────────────────────────────────────────────────────────
export interface TradeItem {
  time: string;        // ISO timestamp
  price: number;
  side: "BUY" | "SELL";
  quantity: number;
  pnl: number | null;
}

export interface TradeListProps {
  trades: TradeItem[];
  height?: number;  // 默认 300
}

// ─── Utilities ────────────────────────────────────────────────────────────────
function formatTime(isoString: string): string {
  try {
    const date = new Date(isoString);
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    const hours = String(date.getHours()).padStart(2, "0");
    const minutes = String(date.getMinutes()).padStart(2, "0");
    return `${month}-${day} ${hours}:${minutes}`;
  } catch {
    return isoString.slice(0, 16);
  }
}

function formatPrice(price: number): string {
  if (price >= 1000) {
    return price.toLocaleString(undefined, { maximumFractionDigits: 2 });
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

function formatPnl(pnl: number | null): { text: string; className: string } {
  if (pnl === null || pnl === undefined) {
    return { text: "-", className: "text-slate-500" };
  }
  if (pnl >= 0) {
    return { text: `+${pnl.toFixed(2)}`, className: "text-green-400" };
  } else {
    return { text: `${pnl.toFixed(2)}`, className: "text-red-400" };
  }
}

// ─── Component ────────────────────────────────────────────────────────────────
export default function TradeList({ trades, height = 300 }: TradeListProps) {
  const endRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const prevLengthRef = useRef(0);

  // 自动滚动到底部（新交易出现时）
  useEffect(() => {
    if (trades.length > prevLengthRef.current && endRef.current) {
      endRef.current.scrollIntoView({ behavior: "smooth" });
    }
    prevLengthRef.current = trades.length;
  }, [trades.length]);

  return (
    <div className="bg-slate-900/50 border border-slate-700 rounded-xl overflow-hidden">
      {/* 表头 */}
      <div className="bg-slate-800 px-3 py-2 border-b border-slate-700">
        <div className="grid grid-cols-5 gap-2 text-xs text-slate-400 font-medium">
          <span>时间</span>
          <span>方向</span>
          <span className="text-right">价格</span>
          <span className="text-right">数量</span>
          <span className="text-right">盈亏</span>
        </div>
      </div>

      {/* 表体 - 滚动区域 */}
      <div 
        ref={containerRef}
        className="overflow-y-auto custom-scrollbar"
        style={{ maxHeight: `${height}px` }}
      >
        {trades.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-slate-500">
            <svg
              className="w-10 h-10 mb-3 opacity-30"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"
              />
            </svg>
            <span className="text-sm">暂无交易记录</span>
          </div>
        ) : (
          <>
            {trades.map((trade, index) => {
              const isLatest = index === trades.length - 1;
              const pnlFormatted = formatPnl(trade.pnl);
              
              return (
                <div
                  key={`${trade.time}-${index}`}
                  className={`
                    grid grid-cols-5 gap-2 px-3 py-2 text-xs border-b border-slate-800/50
                    hover:bg-slate-800/30 transition-colors
                    ${isLatest ? "animate-highlight-fade" : ""}
                  `}
                >
                  <span className="text-slate-400 font-mono truncate">
                    {formatTime(trade.time)}
                  </span>
                  <span className={trade.side === "BUY" ? "text-green-400" : "text-red-400"}>
                    {trade.side === "BUY" ? "买入" : "卖出"}
                  </span>
                  <span className="text-slate-300 font-mono text-right">
                    {formatPrice(trade.price)}
                  </span>
                  <span className="text-slate-400 font-mono text-right">
                    {formatQuantity(trade.quantity)}
                  </span>
                  <span className={`font-mono font-medium text-right ${pnlFormatted.className}`}>
                    {pnlFormatted.text}
                  </span>
                </div>
              );
            })}
            <div ref={endRef} />
          </>
        )}
      </div>

      {/* 底部统计 */}
      {trades.length > 0 && (
        <div className="bg-slate-800/50 px-3 py-2 border-t border-slate-700">
          <div className="flex items-center justify-between text-xs">
            <span className="text-slate-500">
              共 <span className="text-slate-300 font-medium">{trades.length}</span> 笔交易
            </span>
            <div className="flex items-center gap-3">
              <span className="text-slate-500">
                买入: <span className="text-green-400">{trades.filter(t => t.side === "BUY").length}</span>
              </span>
              <span className="text-slate-500">
                卖出: <span className="text-red-400">{trades.filter(t => t.side === "SELL").length}</span>
              </span>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
