import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { TrendingUp, Clock, X } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface MarketConfigPanelProps {
  symbol: string;
  setSymbol: (val: string) => void;
  interval: string;
  setIntervalVal: (val: string) => void;
  limit: number;
  setLimit: (val: number) => void;
  startTime: string;
  setStartTime: (val: string) => void;
  endTime: string;
  setEndTime: (val: string) => void;
  initialCapital: number;
  setInitialCapital: (val: number) => void;
  symbols: { value: string; label: string }[];
  intervals: { value: string; label: string }[];
  limitOptions: { value: number; label: string }[];
  accentColor?: "blue" | "purple" | "green" | "orange";
}

export function MarketConfigPanel({
  symbol, setSymbol,
  interval, setIntervalVal,
  limit, setLimit,
  startTime, setStartTime,
  endTime, setEndTime,
  initialCapital, setInitialCapital,
  symbols, intervals, limitOptions,
  accentColor = "blue"
}: MarketConfigPanelProps) {

  const getAccentStyles = () => {
    const baseIcon = {
      iconBg: "bg-green-500/10",
      iconBorder: "border-green-500/20",
      iconText: "text-green-400",
    };

    switch (accentColor) {
      case "purple":
        return {
          ...baseIcon,
          btnActiveBg: "bg-purple-600/20",
          btnActiveBorder: "border-purple-500/50",
          btnActiveText: "text-purple-400",
          inputFocus: "focus:ring-purple-500 focus:border-purple-500",
        };
      case "orange":
        return {
          ...baseIcon,
          btnActiveBg: "bg-orange-600/20",
          btnActiveBorder: "border-orange-500/50",
          btnActiveText: "text-orange-400",
          inputFocus: "focus:ring-orange-500 focus:border-orange-500",
        };
      case "green":
        return {
          ...baseIcon,
          btnActiveBg: "bg-green-600/20",
          btnActiveBorder: "border-green-500/50",
          btnActiveText: "text-green-400",
          inputFocus: "focus:ring-green-500 focus:border-green-500",
        };
      case "blue":
      default:
        return {
          ...baseIcon,
          btnActiveBg: "bg-blue-600/20",
          btnActiveBorder: "border-blue-500/50",
          btnActiveText: "text-blue-400",
          inputFocus: "focus:ring-blue-500 focus:border-blue-500",
        };
    }
  };

  const styles = getAccentStyles();

  return (
    <Card className="bg-slate-900 border-slate-700/50">
      <CardHeader className="pb-3">
        <CardTitle className="text-slate-100 text-sm flex items-center gap-2">
          <div className={`w-6 h-6 rounded flex items-center justify-center border ${styles.iconBg} ${styles.iconBorder}`}>
            <TrendingUp className={`w-3.5 h-3.5 ${styles.iconText}`} />
          </div>
          回测配置
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div>
          <label className="text-xs text-slate-400 mb-1.5 block">交易对</label>
          <Select value={symbol} onValueChange={setSymbol}>
            <SelectTrigger className="w-full bg-slate-800 border-slate-700 text-slate-100 h-9 text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-slate-800 border-slate-700">
              {symbols.map(s => (
                <SelectItem key={s.value} value={s.value} className="text-slate-100 focus:bg-slate-700 cursor-pointer">{s.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div>
          <label className="text-xs text-slate-400 mb-1.5 block">K线周期</label>
          <Select value={interval} onValueChange={setIntervalVal}>
            <SelectTrigger className="w-full bg-slate-800 border-slate-700 text-slate-100 h-9 text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-slate-800 border-slate-700">
              {intervals.map(i => (
                <SelectItem key={i.value} value={i.value} className="text-slate-100 focus:bg-slate-700 cursor-pointer">{i.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div>
          <label className="text-xs text-slate-400 mb-1.5 block">K线数量</label>
          <Select value={String(limit)} onValueChange={v => setLimit(Number(v))}>
            <SelectTrigger className="w-full bg-slate-800 border-slate-700 text-slate-100 h-9 text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-slate-800 border-slate-700">
              {limitOptions.map(o => (
                <SelectItem key={o.value} value={String(o.value)} className="text-slate-100 focus:bg-slate-700 cursor-pointer">{o.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        {/* Date Range Selector */}
        <div className="pt-2 border-t border-slate-700/50">
          <div className="flex items-center justify-between mb-2">
            <label className="text-xs text-slate-400 flex items-center gap-1.5">
              <Clock className="w-3.5 h-3.5" />
              日期范围（可选）
            </label>
            {(startTime || endTime) && (
              <button
                onClick={() => { setStartTime(''); setEndTime(''); }}
                className="text-[10px] text-slate-500 hover:text-slate-300 flex items-center gap-1 transition-colors"
              >
                <X className="w-3 h-3" />
                清除
              </button>
            )}
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-[10px] text-slate-500 mb-1 block">开始时间</label>
              <input
                type="datetime-local"
                value={startTime}
                onChange={e => setStartTime(e.target.value)}
                className={`w-full bg-slate-800 border border-slate-700 rounded-lg px-2 py-1.5 text-xs text-slate-100 focus:outline-none focus:ring-1 ${styles.inputFocus}`}
              />
            </div>
            <div>
              <label className="text-[10px] text-slate-500 mb-1 block">结束时间</label>
              <input
                type="datetime-local"
                value={endTime}
                onChange={e => setEndTime(e.target.value)}
                className={`w-full bg-slate-800 border border-slate-700 rounded-lg px-2 py-1.5 text-xs text-slate-100 focus:outline-none focus:ring-1 ${styles.inputFocus}`}
              />
            </div>
          </div>
          <p className="text-[10px] text-slate-500 mt-2">
            {startTime && endTime
              ? "将使用指定时间范围内的历史数据"
              : "默认使用最近 N 根 K 线数据"}
          </p>
        </div>
        <div>
          <label className="text-xs text-slate-400 mb-1.5 block">初始资金 (USDT)</label>
          <div className="flex gap-2">
            {[5000, 10000, 50000].map(v => (
              <button
                key={v}
                onClick={() => setInitialCapital(v)}
                className={`flex-1 py-1.5 text-xs rounded-lg border transition-all ${
                  initialCapital === v
                    ? `${styles.btnActiveBg} ${styles.btnActiveBorder} ${styles.btnActiveText}`
                    : "bg-slate-800 border-slate-700 text-slate-400 hover:text-slate-200"
                }`}
              >
                {v >= 1000 ? `${v / 1000}K` : v}
              </button>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
