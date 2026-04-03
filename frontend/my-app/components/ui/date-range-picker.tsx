"use client";

import { useState, useEffect } from "react";
import { format, subDays, startOfDay, endOfDay, isSameDay } from "date-fns";
import { Calendar as CalendarIcon, Clock, ChevronDown, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";

interface DateRange {
  start: string; // ISO string
  end: string;   // ISO string
}

interface DateRangePickerProps {
  value: DateRange;
  onChange: (value: DateRange) => void;
  validDates?: string[]; // Array of YYYY-MM-DD strings
  quickRanges?: { label: string; days: number }[]; // 动态快捷选项
  minDate?: Date | null; // 可选：最小有效日期
  maxDate?: Date | null; // 可选：最大有效日期
  className?: string;
}

interface QuickRange {
  label: string;
  days: number;
}

// 根据可用数据天数生成合适的快捷选项
export function generateQuickRanges(validDates: string[] | undefined, interval: string): QuickRange[] {
  if (!validDates || validDates.length === 0) {
    // 默认选项，根据周期类型返回
    if (interval.endsWith('m')) {
      // 分钟级别周期：更短的默认选项
      return [
        { label: "近 1 天", days: 1 },
        { label: "近 3 天", days: 3 },
        { label: "近 7 天", days: 7 },
      ];
    } else {
      // 小时/天级别周期
      return [
        { label: "近 7 天", days: 7 },
        { label: "近 14 天", days: 14 },
        { label: "近 30 天", days: 30 },
      ];
    }
  }
  
  // 计算实际可用天数
  const minDate = new Date(validDates[0]);
  const maxDate = new Date(validDates[validDates.length - 1]);
  const availableDays = Math.ceil((maxDate.getTime() - minDate.getTime()) / (1000 * 60 * 60 * 24)) + 1;
  
  if (interval.endsWith('m')) {
    // 分钟级别周期：1-7天范围内
    if (availableDays <= 1) {
      return [{ label: "近 1 天", days: 1 }];
    } else if (availableDays <= 3) {
      return [
        { label: "近 1 天", days: 1 },
        { label: `近 ${availableDays} 天`, days: availableDays },
      ];
    } else {
      return [
        { label: "近 1 天", days: 1 },
        { label: "近 3 天", days: 3 },
        { label: `近 ${Math.min(7, availableDays)} 天`, days: Math.min(7, availableDays) },
      ];
    }
  } else if (interval.endsWith('h')) {
    // 小时级别周期：7-30天范围内
    if (availableDays <= 7) {
      return [
        { label: `近 ${availableDays} 天`, days: availableDays },
      ];
    } else if (availableDays <= 14) {
      return [
        { label: "近 7 天", days: 7 },
        { label: `近 ${availableDays} 天`, days: availableDays },
      ];
    } else {
      return [
        { label: "近 7 天", days: 7 },
        { label: "近 14 天", days: 14 },
        { label: `近 ${Math.min(30, availableDays)} 天`, days: Math.min(30, availableDays) },
      ];
    }
  } else {
    // 天级别周期：30-180天范围
    if (availableDays <= 30) {
      return [
        { label: `近 ${availableDays} 天`, days: availableDays },
      ];
    } else if (availableDays <= 60) {
      return [
        { label: "近 30 天", days: 30 },
        { label: `近 ${availableDays} 天`, days: availableDays },
      ];
    } else {
      return [
        { label: "近 30 天", days: 30 },
        { label: "近 60 天", days: 60 },
        { label: `近 ${Math.min(180, availableDays)} 天`, days: Math.min(180, availableDays) },
      ];
    }
  }
}

export function DateRangePicker({ 
  value, 
  onChange, 
  validDates, 
  quickRanges,
  minDate,
  maxDate,
  className 
}: DateRangePickerProps) {
  const [mounted, setMounted] = useState(false);
  const [date, setDate] = useState<{
    from: Date | undefined;
    to: Date | undefined;
  }>({
    from: undefined,
    to: undefined,
  });

  // Set initial date only on client mount to avoid hydration mismatch
  useEffect(() => {
    setMounted(true);
    setDate({
      from: new Date(value.start),
      to: new Date(value.end),
    });
  }, []);

  useEffect(() => {
    if (mounted) {
      setDate({
        from: new Date(value.start),
        to: new Date(value.end),
      });
    }
  }, [value.start, value.end, mounted]);

  const handleSelect = (range: { from: Date | undefined; to: Date | undefined } | undefined) => {
    if (!range) return;
    setDate(range);
    if (range.from && range.to) {
      onChange({
        start: range.from.toISOString(),
        end: range.to.toISOString(),
      });
    } else if (range.from) {
      // If only from is selected, we might want to wait for to, 
      // or just update start and keep end as is (or same as start)
      onChange({
        ...value,
        start: range.from.toISOString(),
      });
    }
  };

  const setQuickRange = (days: number) => {
    // 使用 maxDate（如果有）作为结束日期，否则使用今天
    const end = maxDate ? new Date(maxDate) : new Date();
    const start = subDays(end, days);
    
    // 确保不早于 minDate
    if (minDate && start < new Date(minDate)) {
      onChange({
        start: new Date(minDate).toISOString(),
        end: end.toISOString(),
      });
    } else {
      onChange({
        start: start.toISOString(),
        end: end.toISOString(),
      });
    }
  };

  // 默认快捷选项
  const defaultQuickRanges = quickRanges || [
    { label: "近 7 天", days: 7 },
    { label: "近 14 天", days: 14 },
    { label: "近 30 天", days: 30 },
  ];

  // Function to check if a date has valid data
  const isDateValid = (day: Date) => {
    if (!validDates || validDates.length === 0) return true;
    const dateStr = format(day, "yyyy-MM-dd");
    return validDates.includes(dateStr);
  };

  return (
    <div className={cn("grid gap-2", className)}>
      <Popover>
        <PopoverTrigger asChild>
          <Button
            id="date"
            variant={"outline"}
            className={cn(
              "w-full justify-start text-left font-normal bg-slate-800 border-slate-700 text-slate-100 h-10 px-3",
              !date && "text-slate-500"
            )}
          >
            <CalendarIcon className="mr-2 h-4 w-4 text-slate-400" />
            {!mounted ? (
              <span className="text-slate-500">加载中...</span>
            ) : date?.from ? (
              date.to ? (
                <>
                  {format(date.from, "LLL dd, y")} -{" "}
                  {format(date.to, "LLL dd, y")}
                </>
              ) : (
                format(date.from, "LLL dd, y")
              )
            ) : (
              <span>选择日期范围</span>
            )}
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-auto p-0 bg-slate-900 border-slate-700 shadow-2xl" align="start">
          <div className="flex flex-col sm:flex-row">
            <div className="p-3 border-r border-slate-800 space-y-2 hidden sm:block w-32">
              <p className="text-[10px] text-slate-500 uppercase font-bold mb-2">快捷选择</p>
              {defaultQuickRanges.map((range) => (
                <Button
                  key={range.label}
                  variant="ghost"
                  className="w-full justify-start text-xs h-8 text-slate-400 hover:text-slate-100 hover:bg-slate-800"
                  onClick={() => setQuickRange(range.days)}
                >
                  {range.label}
                </Button>
              ))}
            </div>
            <div className="p-2">
               <Calendar
                initialFocus
                mode="range"
                defaultMonth={date?.from}
                selected={date}
                onSelect={(range: any) => handleSelect(range)}
                numberOfMonths={2}
                disabled={(day) => !isDateValid(day)}
                className="rounded-md border-0"
                modifiers={{
                  hasData: (day) => isDateValid(day),
                }}
                modifiersClassNames={{
                  hasData: "after:content-[''] after:absolute after:bottom-1 after:left-1/2 after:-translate-x-1/2 after:w-1 after:h-1 after:bg-blue-500 after:rounded-full",
                }}
              />
            </div>
          </div>
          <div className="p-3 border-t border-slate-800 bg-slate-900/50 flex items-center justify-between">
            <span className="text-[10px] text-slate-500 flex items-center gap-1">
              <Clock className="w-3 h-3" />
              当前显示为本地时区，提交时将自动转换为 UTC
            </span>
            {validDates && validDates.length > 0 && (
              <div className="flex items-center gap-2">
                <div className="w-1.5 h-1.5 bg-blue-500 rounded-full" />
                <span className="text-[10px] text-slate-500">有数据日期</span>
              </div>
            )}
          </div>
        </PopoverContent>
      </Popover>
      
      {/* Mobile Quick Selectors */}
      <div className="flex gap-1.5 sm:hidden overflow-x-auto pb-1 custom-scrollbar">
        {defaultQuickRanges.map(range => (
          <button
            key={range.label}
            onClick={() => setQuickRange(range.days)}
            className="px-2.5 py-1 text-[10px] bg-slate-800 border border-slate-700 text-slate-400 rounded-md hover:bg-slate-700 hover:text-slate-100 transition-all whitespace-nowrap"
          >
            {range.label}
          </button>
        ))}
      </div>
    </div>
  );
}
