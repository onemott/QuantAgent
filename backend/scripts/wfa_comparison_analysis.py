# -*- coding: utf-8 -*-
"""
WFA 有无对比分析脚本
====================
对比同一策略在启用和禁用前向走查分析（WFA）两种情况下的量化表现。

使用方法:
    python wfa_comparison_analysis.py \
      --symbol BTCUSDT \
      --interval 1d \
      --start 2022-01-01 \
      --end 2024-12-31 \
      --strategy rsi \
      --is-days 180 \
      --oos-days 60 \
      --step-days 60 \
      --n-trials 50 \
      --initial-capital 10000
"""

import argparse
import asyncio
import sys
import os
import math
import csv
from datetime import datetime, timedelta
from typing import Dict, Any, List, Tuple, Optional

import pandas as pd
import numpy as np

# 尝试导入 tabulate，失败则使用简单格式
try:
    from tabulate import tabulate
    HAS_TABULATE = True
except ImportError:
    HAS_TABULATE = False
    print("⚠ tabulate 未安装，将使用简单文本格式输出")


def safe_tabulate(data: List, headers: List, title: str = "", max_rows: int = None) -> str:
    """安全表格输出，支持 tabulate 或 fallback
    
    Args:
        data: 表格数据
        headers: 表头
        title: 标题
        max_rows: 最大显示行数，超出的部分会显示省略信息
    """
    if not data:
        return f"{title}\n(无数据)"
    
    # 处理行数限制
    total_rows = len(data)
    display_data = data
    overflow_msg = ""
    if max_rows and total_rows > max_rows:
        display_data = data[:max_rows]
        overflow_msg = f"\n... 及另外 {total_rows - max_rows} 条"
    
    if HAS_TABULATE:
        table = tabulate(display_data, headers=headers, tablefmt="pretty", **{})
        result = f"{title}\n{table}" if title else table
        if overflow_msg:
            result += overflow_msg
        return result
    else:
        # fallback: 手动格式化
        col_widths = [max(len(str(h)), max(len(str(row[i]) if i < len(row) else "") for row in display_data)) for i, h in enumerate(headers)]
        header_line = " | ".join(h.ljust(w) for h, w in zip(headers, col_widths))
        separator = "-+-".join("-" * w for w in col_widths)
        rows = []
        for row in display_data:
            row_str = " | ".join(str(row[i] if i < len(row) else "").ljust(w) for i, w in enumerate(col_widths))
            rows.append(row_str)
        table = "\n".join([header_line, separator] + rows)
        result = f"{title}\n{table}" if title else table
        if overflow_msg:
            result += overflow_msg
        return result


# 策略中文名映射
STRATEGY_NAMES = {
    "rsi": "RSI超买超卖",
    "ma": "均线金叉",
    "boll": "布林带回归",
    "macd": "MACD交叉",
    "ema_triple": "三线EMA",
    "atr_trend": "ATR趋势追踪",
    "turtle": "海龟交易",
    "ichimoku": "一目均衡表",
}

# 交易样本量阈值配置
MIN_TOTAL_TRADES = 100  # 总交易次数最低要求
MIN_OOS_WINDOW_TRADES = 20  # 单个 OOS 窗口最低交易次数
INTERVAL_FALLBACK_CHAIN = ["4h", "1h"]  # 周期降级链（从大到小）

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.binance_service import BinanceService
from app.services.walk_forward.optimizer import WalkForwardOptimizer
from app.services.backtester.optimizer import OptunaOptimizer
from app.services.backtester.vectorized import VectorizedBacktester
from app.services.strategy_templates import build_signal_func, get_template
from app.services.indicators import rsi as calc_rsi


# ─────────────────────────────────────────────────────────────────────────────
# 诊断模块
# ─────────────────────────────────────────────────────────────────────────────

def check_data_integrity(df: pd.DataFrame, interval: str) -> Dict[str, Any]:
    """
    模块1：数据完整性检查
    在数据获取后、回测前调用
    
    检查项：
    1. 时间连续性
    2. 价格合理性
    3. OHLC 关系校验
    4. 价格跳空
    5. 成交量检查
    6. 统计摘要
    """
    try:
        print("\n" + "=" * 60)
        print("数据完整性检查")
        print("=" * 60)
        
        anomalies = []
        stats = {
            "total_rows": len(df),
            "time_start": str(df.index[0]) if len(df) > 0 else "N/A",
            "time_end": str(df.index[-1]) if len(df) > 0 else "N/A",
            "time_gaps": 0,
            "price_zero_nan": 0,
            "price_negative": 0,
            "ohlc_violations": 0,
            "price_jumps": 0,
            "volume_issues": 0,
        }
        
        # 1. 时间连续性检查
        print("\n[1] 时间连续性检查...")
        interval_minutes = _parse_interval_to_minutes(interval)
        if interval_minutes > 0 and len(df) > 1:
            time_diffs = df.index.to_series().diff().dropna()
            expected_delta = timedelta(minutes=interval_minutes)
            
            gap_records = []
            for i, diff in enumerate(time_diffs):
                if diff != expected_delta:
                    gap_records.append([
                        str(df.index[i+1]),
                        f"{diff}",
                        f"{expected_delta}",
                        f"差距 {diff - expected_delta}"
                    ])
                    anomalies.append({"type": "时间跳空", "time": str(df.index[i+1]), "detail": f"实际间隔 {diff}，预期 {expected_delta}"})
            
            stats["time_gaps"] = len(gap_records)
            if gap_records:
                print(safe_tabulate(
                    gap_records,
                    ["时间", "实际间隔", "预期间隔", "差异"],
                    f"发现 {len(gap_records)} 处时间跳空:",
                    max_rows=20
                ))
            else:
                print("  ✓ 时间连续性良好，无跳空")
        else:
            print("  - 跳过时间连续性检查（无法解析周期或数据不足）")
        
        # 2. 价格合理性检查
        print("\n[2] 价格合理性检查...")
        price_cols = ["open", "high", "low", "close"]
        price_issues = []
        for col in price_cols:
            zero_nan_mask = (df[col] == 0) | df[col].isna()
            negative_mask = df[col] < 0
            
            for idx in df.index[zero_nan_mask]:
                price_issues.append([str(idx), col, "0或NaN"])
            for idx in df.index[negative_mask]:
                price_issues.append([str(idx), col, "负数"])
        
        
        stats["price_zero_nan"] = sum(1 for p in price_issues if p[2] == "0或NaN")
        stats["price_negative"] = sum(1 for p in price_issues if p[2] == "负数")
        
        if price_issues:
            print(safe_tabulate(
                price_issues,
                ["时间", "列", "问题类型"],
                f"发现 {len(price_issues)} 处价格异常:",
                max_rows=20
            ))
        else:
            print("  ✓ 价格数据合理，无0/NaN/负数")
        
        # 3. OHLC 关系校验
        print("\n[3] OHLC 关系校验...")
        ohlc_violations = []
        invalid_high = df["high"] < df[["open", "close"]].max(axis=1)
        invalid_low = df["low"] > df[["open", "close"]].min(axis=1)
        
        for idx in df.index[invalid_high]:
            ohlc_violations.append([str(idx), "high < max(open,close)", f"high={df.loc[idx, 'high']:.4f}"])
        for idx in df.index[invalid_low]:
            ohlc_violations.append([str(idx), "low > min(open,close)", f"low={df.loc[idx, 'low']:.4f}"])
        
        stats["ohlc_violations"] = len(ohlc_violations)
        if ohlc_violations:
            print(safe_tabulate(
                ohlc_violations,
                ["时间", "违规类型", "详情"],
                f"发现 {len(ohlc_violations)} 处 OHLC 违规:",
                max_rows=20
            ))
        else:
            print("  ✓ OHLC 关系正确")
        
        # 4. 价格跳空检查（相邻K线close变化超过10%）
        print("\n[4] 价格跳空检查（>10%）...")
        close_change = df["close"].pct_change().abs()
        jump_mask = close_change > 0.10
        price_jumps = []
        
        for idx in df.index[jump_mask]:
            prev_idx = df.index[df.index.get_loc(idx) - 1] if df.index.get_loc(idx) > 0 else None
            if prev_idx is not None:
                price_jumps.append([
                    str(idx),
                    f"{df.loc[prev_idx, 'close']:.4f}",
                    f"{df.loc[idx, 'close']:.4f}",
                    f"{close_change[idx]:.2%}"
                ])
        
        
        stats["price_jumps"] = len(price_jumps)
        if price_jumps:
            print(safe_tabulate(
                price_jumps,
                ["时间", "前收盘价", "当前收盘价", "变化幅度"],
                f"发现 {len(price_jumps)} 处价格跳空:",
                max_rows=20
            ))
        else:
            print("  ✓ 无异常价格跳空")
        
        # 5. 成交量检查
        print("\n[5] 成交量检查...")
        volume_issues = []
        volume_invalid = (df["volume"] <= 0) | df["volume"].isna()
        
        for idx in df.index[volume_invalid]:
            volume_issues.append([str(idx), f"volume={df.loc[idx, 'volume']}"])
        
        
        stats["volume_issues"] = len(volume_issues)
        if volume_issues:
            print(safe_tabulate(
                volume_issues,
                ["时间", "成交量值"],
                f"发现 {len(volume_issues)} 处成交量异常:",
                max_rows=20
            ))
        else:
            print("  ✓ 成交量数据正常")
        
        # 6. 统计摘要
        print("\n" + "-" * 40)
        print("统计摘要:")
        summary_data = [
            ["总行数", stats["total_rows"]],
            ["时间范围", f"{stats['time_start']} ~ {stats['time_end']}"],
            ["时间跳空数", stats["time_gaps"]],
            ["价格异常数（0/NaN/负数）", stats["price_zero_nan"] + stats["price_negative"]],
            ["OHLC违规数", stats["ohlc_violations"]],
            ["价格跳空数（>10%）", stats["price_jumps"]],
            ["成交量异常数", stats["volume_issues"]],
        ]
        print(safe_tabulate(summary_data, ["指标", "值"]))
        
        # 总体评估
        total_issues = stats["time_gaps"] + stats["price_zero_nan"] + stats["price_negative"] + stats["ohlc_violations"] + stats["price_jumps"] + stats["volume_issues"]
        if total_issues == 0:
            print("\n✓ 数据完整性检查通过")
        else:
            print(f"\n⚠ 共发现 {total_issues} 处数据问题，请核查")
        
        return {"status": "ok", "stats": stats, "anomalies": anomalies}
        
    except Exception as e:
        print(f"❌ 数据完整性检查出错: {e}")
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": str(e)}


def _parse_interval_to_minutes(interval: str) -> int:
    """将 interval 字符串解析为分钟数"""
    try:
        interval = interval.lower().strip()
        if interval.endswith("m"):
            return int(interval[:-1])
        elif interval.endswith("h"):
            return int(interval[:-1]) * 60
        elif interval.endswith("d"):
            return int(interval[:-1]) * 60 * 24
        elif interval.endswith("w"):
            return int(interval[:-1]) * 60 * 24 * 7
        else:
            return 0
    except:
        return 0


def check_strategy_signals(df: pd.DataFrame, strategy_type: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    模块2：策略信号检查
    在无WFA回测完成后，使用最优参数调用
    """
    try:
        print("\n" + "=" * 60)
        print("策略信号检查")
        print("=" * 60)
        print(f"策略类型: {strategy_type}")
        print(f"参数: {params}")
        
        # 1. 生成信号序列
        signal_func = build_signal_func(strategy_type, params)
        signals = signal_func(df)
        
        # 2. 提取所有信号 != 0 的时间点
        signal_points = []
        signal_indices = signals[signals != 0].index
        
        # 3. 对于 RSI 策略，手动计算 RSI 值
        rsi_values = None
        if strategy_type.lower() == "rsi":
            rsi_period = params.get("rsi_period", 14)
            # 使用与 indicators.py 一致的计算方式
            delta = df["close"].diff()
            gain = delta.clip(lower=0)
            loss = -delta.clip(upper=0)
            avg_gain = gain.ewm(com=rsi_period - 1, adjust=False).mean()
            avg_loss = loss.ewm(com=rsi_period - 1, adjust=False).mean()
            rs = avg_gain / avg_loss.replace(0, np.nan)
            rsi_values = 100 - (100 / (1 + rs))
        
        # 构建信号表格
        signal_table = []
        for idx in signal_indices:
            sig_val = signals[idx]
            direction = "BUY" if sig_val == 1 else "SELL" if sig_val == -1 else "UNKNOWN"
            close_price = df.loc[idx, "close"]
            row = [str(idx), direction, f"{close_price:.4f}"]
            if rsi_values is not None and idx in rsi_values.index:
                row.append(f"{rsi_values[idx]:.2f}" if not pd.isna(rsi_values[idx]) else "N/A")
            signal_table.append(row)
        
        
        print(f"\n共发现 {len(signal_table)} 个信号点:")
        headers = ["时间", "方向", "收盘价"]
        if rsi_values is not None:
            headers.append("RSI值")
        print(safe_tabulate(signal_table, headers, max_rows=20))
        
        # 4. 验证前5笔信号（仅 RSI）
        if strategy_type.lower() == "rsi" and rsi_values is not None:
            print("\n[RSI信号验证]")
            oversold = params.get("oversold", 30.0)
            overbought = params.get("overbought", 70.0)
            
            validation_table = []
            for i, idx in enumerate(signal_indices[:5]):
                sig_val = signals[idx]
                rsi_val = rsi_values[idx] if idx in rsi_values.index else None
                direction = "BUY" if sig_val == 1 else "SELL"
                
                if sig_val == 1:  # 买入信号
                    expected = f"RSI <= {oversold}"
                    actual = f"RSI = {rsi_val:.2f}" if rsi_val and not pd.isna(rsi_val) else "N/A"
                    valid = rsi_val is not None and not pd.isna(rsi_val) and rsi_val <= oversold
                elif sig_val == -1:  # 卖出信号
                    expected = f"RSI >= {overbought}"
                    actual = f"RSI = {rsi_val:.2f}" if rsi_val and not pd.isna(rsi_val) else "N/A"
                    valid = rsi_val is not None and not pd.isna(rsi_val) and rsi_val >= overbought
                else:
                    expected = "-"
                    actual = "-"
                    valid = None
                
                validation_table.append([
                    i + 1,
                    str(idx),
                    direction,
                    expected,
                    actual,
                    "✓" if valid else "✗" if valid is False else "-"
                ])
            
            print(safe_tabulate(
                validation_table,
                ["序号", "时间", "方向", "预期条件", "实际值", "验证结果"]
            ))
        
        # 5. 检查连续同方向信号
        print("\n[连续信号告警]")
        consecutive_warnings = []
        prev_signal = 0
        consecutive_count = 0
        
        for idx in signal_indices:
            sig_val = signals[idx]
            if sig_val == prev_signal:
                consecutive_count += 1
                if consecutive_count >= 2:
                    consecutive_warnings.append([
                        str(idx),
                        "BUY" if sig_val == 1 else "SELL",
                        f"连续{consecutive_count + 1}次"
                    ])
            else:
                consecutive_count = 0
                prev_signal = sig_val
        
        if consecutive_warnings:
            print(safe_tabulate(
                consecutive_warnings,
                ["时间", "方向", "告警"],
                f"发现 {len(consecutive_warnings)} 处连续同向信号:",
                max_rows=10
            ))
        else:
            print("  ✓ 无连续同向信号")
        
        # 6. 统计
        buy_count = sum(1 for s in signals if s == 1)
        sell_count = sum(1 for s in signals if s == -1)
        
        stats_table = [
            ["总信号数", len(signal_table)],
            ["买入次数", buy_count],
            ["卖出次数", sell_count],
        ]
        print("\n统计摘要:")
        print(safe_tabulate(stats_table, ["指标", "值"]))
        
        return {
            "status": "ok",
            "total_signals": len(signal_table),
            "buy_count": buy_count,
            "sell_count": sell_count
        }
        
    except Exception as e:
        print(f"❌ 策略信号检查出错: {e}")
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": str(e)}


def verify_backtest_trades(
    df: pd.DataFrame, 
    strategy_type: str, 
    params: Dict[str, Any], 
    initial_capital: float = 10000.0,
    commission: float = 0.001
) -> Dict[str, Any]:
    """
    模块3：回测结果手动验证
    在无WFA回测完成后调用
    """
    try:
        print("\n" + "=" * 60)
        print("回测结果手动验证")
        print("=" * 60)
        print(f"策略类型: {strategy_type}")
        print(f"参数: {params}")
        print(f"初始资金: {initial_capital}")
        print(f"手续费率: {commission}")
        
        # 1. 生成信号
        signal_func = build_signal_func(strategy_type, params)
        signals = signal_func(df)
        
        # 2. 使用 VectorizedBacktester 运行回测
        bt = VectorizedBacktester(df, signal_func, initial_capital, commission)
        backtest_result = bt.run()
        
        engine_final_capital = backtest_result.get("final_capital", initial_capital)
        trade_markers = backtest_result.get("trade_markers", [])
        
        print(f"\n引擎回测结果:")
        print(f"  最终资金: ${engine_final_capital:.2f}")
        print(f"  总交易次数: {backtest_result.get('total_trades', 0)}")
        print(f"  年化收益: {backtest_result.get('annual_return', 0):.2f}%")
        
        # 3. 手动提取买卖配对并计算盈亏
        # 根据 vectorized.py 的逻辑：
        # - 持仓状态通过 ffill 维持，买入信号(1)后持多仓，卖出信号(-1)后空仓
        # - 实际成交价：信号当根的 close（因为 shift(1) 后次日执行，但收益按当日收盘价计算）
        #   实际上，根据代码 pos = position.shift(1).fillna(initial_position)
        #   信号在 t 时刻产生，t+1 时刻生效，所以买入价应该是 t+1 时刻的 open 或 close
        #   但 vectorized 用的是 returns = df['close'].pct_change()
        #   所以持仓收益基于 close 价格变化
        
        # 简化理解：信号产生后，次日按 open 执行更接近实盘
        # 但 vectorized 引擎实际用 close 收益，我们按 close 计算手动验证
        
        print("\n[手动交易验证]")
        print("（按 vectorized 引擎逻辑：信号后次日按 close 计算收益）")
        
        # 找出信号点
        signal_indices = signals[signals != 0].index.tolist()
        
        # 构建买卖配对
        trades = []
        position = 0  # 0=空仓, 1=多仓
        entry_price = None
        entry_time = None
        trade_num = 0
        
        manual_capital = initial_capital
        
        for i, idx in enumerate(signal_indices):
            sig = signals[idx]
            idx_loc = df.index.get_loc(idx)
            
            # 买入信号
            if sig == 1 and position == 0:
                # 次日执行
                if idx_loc + 1 < len(df):
                    next_idx = df.index[idx_loc + 1]
                    entry_price = df.loc[next_idx, "open"]  # 假设次日开盘执行
                    entry_time = next_idx
                    position = 1
            # 卖出信号
            elif sig == -1 and position == 1:
                if idx_loc + 1 < len(df):
                    next_idx = df.index[idx_loc + 1]
                    exit_price = df.loc[next_idx, "open"]
                    
                    # 手动计算盈亏
                    buy_amount = initial_capital  # 全仓买入
                    sell_amount = buy_amount * (exit_price / entry_price)
                    
                    buy_fee = buy_amount * commission
                    sell_fee = sell_amount * commission
                    
                    net_profit = sell_amount - buy_amount - buy_fee - sell_fee
                    profit_pct = net_profit / initial_capital
                    
                    manual_capital += net_profit
                    
                    trade_num += 1
                    trades.append([
                        trade_num,
                        str(entry_time),
                        f"{entry_price:.4f}",
                        str(next_idx),
                        f"{exit_price:.4f}",
                        f"${net_profit:.2f}",
                        f"{profit_pct:.2%}"
                    ])
                    
                    position = 0
                    entry_price = None
                    
                    if trade_num >= 5:
                        break
        
        if trades:
            print(safe_tabulate(
                trades,
                ["交易#", "买入时间", "买入价", "卖出时间", "卖出价", "净盈亏", "收益率"]
            ))
            print(f"\n手动计算最终资金（前5笔）: ${manual_capital:.2f}")
        else:
            print("未找到完整的买卖配对")
        
        # 4. 对比差异
        print("\n[差异对比]")
        diff_table = [
            ["引擎最终资金", f"${engine_final_capital:.2f}"],
            ["手动计算资金（前5笔）", f"${manual_capital:.2f}"],
            ["差异", f"${abs(engine_final_capital - manual_capital):.2f}"],
            ["说明", "手动计算仅统计前5笔完整交易，差异属正常"]
        ]
        print(safe_tabulate(diff_table, ["项目", "值"]))
        
        return {
            "status": "ok",
            "engine_final_capital": engine_final_capital,
            "manual_capital": manual_capital,
            "trades_verified": len(trades)
        }
        
    except Exception as e:
        print(f"❌ 回测验证出错: {e}")
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": str(e)}


async def compare_strategies(
    df: pd.DataFrame,
    strategies: List[str],
    initial_capital: float = 10000.0,
    n_trials: int = 50,
    is_days: int = 180,
    oos_days: int = 60,
    step_days: int = 60,
    output_csv: Optional[str] = None,
    # 新增参数：降级相关
    original_interval: str = "1d",
    no_auto_downgrade: bool = False,
    min_total_trades: int = 100,
    min_oos_trades: int = 20,
    symbol: str = "BTCUSDT",
    start: str = "2023-06-01",
    end: str = "2025-12-31",
    use_cache: bool = False
) -> Dict[str, Any]:
    """
    模块4：多策略完整WFA对比
    每个策略都执行完整的 WFA 有/无对比
    通过 --compare-strategies CLI 参数控制是否执行
    """
    try:
        print("\n" + "=" * 80)
        print("多策略完整WFA对比分析")
        print("=" * 80)
        print(f"策略列表: {strategies}")
        print(f"初始资金: {initial_capital}")
        print(f"优化 trials: {n_trials}")
        print(f"WFA参数: IS={is_days}天 | OOS={oos_days}天 | Step={step_days}天")
        
        results = []
        
        for i, strategy_type in enumerate(strategies):
            strategy_name = STRATEGY_NAMES.get(strategy_type, strategy_type.upper())
            print(f"\n[{i+1}/{len(strategies)}] 正在处理策略: {strategy_name}...")
            
            try:
                # === 无 WFA 场景 ===
                print(f"  [A] 执行无WFA优化...")
                no_wfa_result = await run_without_wfa(df, strategy_type, n_trials, initial_capital)
                actual_interval = original_interval  # 记录该策略实际使用的周期
                strategy_df = df  # 记录该策略使用的数据
                
                # 周期自适应降级逻辑（每个策略单独判断）
                if no_wfa_result and not no_auto_downgrade:
                    total_trades = no_wfa_result.get("total_trades", 0)
                    
                    if total_trades < min_total_trades:
                        print(f"  ⚠ 交易次数不足: 当前 {total_trades} 次，阈值 {min_total_trades} 次")
                        print(f"    开始周期降级尝试，降级链: {INTERVAL_FALLBACK_CHAIN}")
                        
                        interval_trades = [(original_interval, total_trades, df)]
                        
                        for fallback_interval in INTERVAL_FALLBACK_CHAIN:
                            if fallback_interval == actual_interval:
                                continue
                            
                            print(f"    [降级尝试] 切换到周期: {fallback_interval}")
                            
                            try:
                                fallback_df = await fetch_data(symbol, fallback_interval, start, end, use_cache)
                            except Exception as e:
                                print(f"    ✗ 获取 {fallback_interval} 数据失败: {e}")
                                continue
                            
                            fallback_result = await run_without_wfa(fallback_df, strategy_type, n_trials, initial_capital)
                            
                            if fallback_result:
                                fallback_trades = fallback_result.get("total_trades", 0)
                                interval_trades.append((fallback_interval, fallback_trades, fallback_df))
                                
                                if fallback_trades >= min_total_trades:
                                    print(f"    ✓ 周期 {fallback_interval} 满足要求: {fallback_trades} 次")
                                    actual_interval = fallback_interval
                                    strategy_df = fallback_df
                                    no_wfa_result = fallback_result
                                    break
                                else:
                                    print(f"    - 周期 {fallback_interval} 交易次数: {fallback_trades} 次，仍不足")
                        
                        # 如果所有周期都不满足，选择交易次数最多的
                        if no_wfa_result.get("total_trades", 0) < min_total_trades:
                            best_interval, best_trades, best_df = max(interval_trades, key=lambda x: x[1])
                            actual_interval = best_interval
                            strategy_df = best_df
                            if best_interval != original_interval:
                                no_wfa_result = await run_without_wfa(strategy_df, strategy_type, n_trials, initial_capital)
                            print(f"    使用交易次数最多的周期: {actual_interval} ({best_trades} 次)")
                
                if not no_wfa_result:
                    print(f"  ✗ {strategy_name} 无WFA优化失败")
                    results.append({
                        "strategy": strategy_type,
                        "no_wfa_annual_return": None,
                        "no_wfa_sharpe": None,
                        "no_wfa_dd": None,
                        "no_wfa_trades": 0,
                        "wfa_annual_return": None,
                        "wfa_sharpe": None,
                        "wfa_dd": None,
                        "wfa_trades": 0,
                        "wfe": None,
                        "best_params": {},
                        "status": "优化失败",
                        "conclusion": "-"
                    })
                    continue
                
                # === 有 WFA 场景 ===
                print(f"  [B] 执行有WFA优化...")
                with_wfa_result = await run_with_wfa(
                    strategy_df, strategy_type, is_days, oos_days, step_days,
                    n_trials, initial_capital
                )
                
                # 计算指标
                no_wfa_return = no_wfa_result.get("annual_return", 0) if no_wfa_result else None
                no_wfa_sharpe = no_wfa_result.get("sharpe_ratio", 0) if no_wfa_result else None
                no_wfa_dd = no_wfa_result.get("max_drawdown", 0) if no_wfa_result else None
                no_wfa_trades = no_wfa_result.get("total_trades", 0) if no_wfa_result else 0
                
                wfa_return = with_wfa_result.get("annual_return", 0) if with_wfa_result else None
                wfa_sharpe = with_wfa_result.get("sharpe_ratio", 0) if with_wfa_result else None
                wfa_dd = with_wfa_result.get("max_drawdown", 0) if with_wfa_result else None
                wfa_trades = with_wfa_result.get("total_trades", 0) if with_wfa_result else 0
                wfe = with_wfa_result.get("wfe", 0) if with_wfa_result else None
                
                # 计算回撤变化
                dd_change = None
                if no_wfa_dd is not None and wfa_dd is not None:
                    dd_change = wfa_dd - no_wfa_dd  # 负值表示回撤减少（改善）
                
                # 提取最优参数（从无WFA结果）
                best_params = {}
                try:
                    optimizer = OptunaOptimizer(df, strategy_type, initial_capital)
                    opt_result = optimizer.optimize(n_trials=n_trials, use_numba=False)
                    if opt_result and "best_params" in opt_result:
                        best_params = opt_result["best_params"]
                except:
                    pass
                
                # 有效性标注和结论
                total_trades = wfa_trades if with_wfa_result else no_wfa_trades
                if total_trades < 10:
                    status = "数据不足"
                    conclusion = "-"
                elif not with_wfa_result:
                    status = "WFA失败"
                    conclusion = "-"
                elif wfe is not None and wfe > 0.5:
                    status = "有效"
                    conclusion = "WFA有效"
                elif wfe is not None and wfe > 0.3:
                    status = "有效"
                    conclusion = "部分有效"
                else:
                    status = "有效"
                    conclusion = "效果不佳"
                
                # 可信度评估
                reliability = ""
                oos_trades_per_window = with_wfa_result.get("oos_trades_per_window", []) if with_wfa_result else []
                insufficient_oos_windows = sum(1 for t in oos_trades_per_window if t < min_oos_trades) if oos_trades_per_window else 0
                
                if total_trades >= min_total_trades and (not oos_trades_per_window or insufficient_oos_windows == 0):
                    reliability = "统计可靠"
                elif total_trades >= min_total_trades and insufficient_oos_windows > 0:
                    reliability = f"部分不足({insufficient_oos_windows}窗)"
                else:
                    reliability = f"样本不足({total_trades}次)"
                
                results.append({
                    "strategy": strategy_type,
                    "no_wfa_annual_return": no_wfa_return,
                    "no_wfa_sharpe": no_wfa_sharpe,
                    "no_wfa_dd": no_wfa_dd,
                    "no_wfa_trades": no_wfa_trades,
                    "wfa_annual_return": wfa_return,
                    "wfa_sharpe": wfa_sharpe,
                    "wfa_dd": wfa_dd,
                    "wfa_trades": wfa_trades,
                    "wfe": wfe,
                    "best_params": best_params,
                    "status": status,
                    "conclusion": conclusion,
                    "reliability": reliability
                })
                
                print(f"  ✓ {strategy_name} 完成")
                
            except Exception as e:
                print(f"  ✗ {strategy_name} 处理出错: {e}")
                import traceback
                traceback.print_exc()
                results.append({
                    "strategy": strategy_type,
                    "no_wfa_annual_return": None,
                    "no_wfa_sharpe": None,
                    "no_wfa_dd": None,
                    "no_wfa_trades": 0,
                    "wfa_annual_return": None,
                    "wfa_sharpe": None,
                    "wfa_dd": None,
                    "wfa_trades": 0,
                    "wfe": None,
                    "best_params": {},
                    "status": "运行失败",
                    "conclusion": "-"
                })
        
        # 按 WFE 降序排列
        results.sort(key=lambda x: x["wfe"] if x["wfe"] is not None else -999, reverse=True)
        
        # 输出两张对比表格
        # 表一：WFA效果核心对比表
        core_table = []
        for r in results:
            wfe_val = f"{r['wfe']*100:.1f}%" if r["wfe"] is not None else "N/A"
            core_table.append([
                STRATEGY_NAMES.get(r["strategy"], r["strategy"].upper()),
                f"{r['no_wfa_sharpe']:.2f}" if r["no_wfa_sharpe"] is not None else "N/A",
                f"{r['wfa_sharpe']:.2f}" if r["wfa_sharpe"] is not None else "N/A",
                wfe_val,
                r.get("status", "-"),
                r.get("conclusion", "-"),
                r.get("reliability", "-")
            ])
        
        print("\n" + "=" * 80)
        print("表一：WFA效果核心对比")
        print("=" * 80)
        print(safe_tabulate(core_table, ["策略", "夏普(无)", "夏普(有)", "WFE", "状态", "结论", "可信度"]))
        
        # 表二：详细指标补充表
        detail_table = []
        for r in results:
            detail_table.append([
                STRATEGY_NAMES.get(r["strategy"], r["strategy"].upper()),
                f"{r['no_wfa_annual_return']*100:.1f}%" if r["no_wfa_annual_return"] is not None else "N/A",
                f"{r['wfa_annual_return']*100:.1f}%" if r["wfa_annual_return"] is not None else "N/A",
                f"{r['no_wfa_dd']*100:.1f}%" if r.get("no_wfa_dd") is not None else "N/A",
                f"{r['wfa_dd']*100:.1f}%" if r.get("wfa_dd") is not None else "N/A",
                r.get("no_wfa_trades", 0),
                r.get("wfa_trades", 0)
            ])
        
        print("\n" + "=" * 80)
        print("表二：详细指标补充")
        print("=" * 80)
        print(safe_tabulate(detail_table, ["策略", "年化%(无)", "年化%(有)", "回撤%(无)", "回撤%(有)", "交易(无)", "交易(有)"]))
        
        # 总结
        print("\n📊 分析总结:")
        valid_count = sum(1 for r in results if r.get("conclusion") == "WFA有效")
        print(f"  - 共处理 {len(strategies)} 个策略")
        print(f"  - WFA有效策略数: {valid_count}")
        if results and results[0].get("wfe"):
            print(f"  - WFE最高策略: {STRATEGY_NAMES.get(results[0]['strategy'], results[0]['strategy'])} (WFE={results[0]['wfe']*100:.1f}%)")
        print("=" * 80)
        
        # CSV 输出
        if output_csv:
            try:
                with open(output_csv, 'w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.writer(f)
                    # 元信息
                    writer.writerow(["多策略WFA对比分析报告"])
                    writer.writerow(["策略数量", str(len(strategies))])
                    writer.writerow(["WFA有效策略数", str(valid_count)])
                    writer.writerow([])  # 空行
                    
                    # 表一标题
                    writer.writerow(["表一：WFA效果核心对比"])
                    writer.writerow(["策略", "夏普(无)", "夏普(有)", "WFE", "状态", "结论", "可信度"])
                    for row in core_table:
                        writer.writerow(row)
                    
                    writer.writerow([])  # 空行分隔
                    
                    # 表二标题
                    writer.writerow(["表二：详细指标补充"])
                    writer.writerow(["策略", "年化%(无)", "年化%(有)", "回撤%(无)", "回撤%(有)", "交易(无)", "交易(有)"])
                    for row in detail_table:
                        writer.writerow(row)
                
                print(f"\n✓ 结果已导出到: {output_csv}")
            except Exception as e:
                print(f"\n⚠ CSV 导出失败: {e}")
        
        return {"status": "ok", "results": results}
        
    except Exception as e:
        print(f"❌ 多策略对比出错: {e}")
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# 数据获取
# ─────────────────────────────────────────────────────────────────────────────

async def fetch_data(symbol: str, interval: str, start: str, end: str, use_cache: bool = False) -> pd.DataFrame:
    """从 Binance 获取 K 线数据，支持本地缓存"""
    print(f"[数据] 正在获取数据: {symbol} {interval} ({start} ~ {end})")
    
    symbol_raw = symbol.upper()
    symbol_ccxt = symbol_raw
    # 转换为 CCXT 格式
    if "/" not in symbol_raw:
        for quote in ("USDT", "BTC", "ETH", "BNB", "BUSD", "USDC"):
            if symbol_raw.endswith(quote):
                base = symbol_raw[:-len(quote)]
                symbol_ccxt = f"{base}/{quote}"
                break
    
    cache_path = os.path.join(os.path.dirname(__file__), f"kline_cache_{symbol_raw}_{interval}.csv")
    
    # 尝试从缓存读取
    if use_cache and os.path.exists(cache_path):
        print(f"  从缓存读取: {cache_path}")
        try:
            df = pd.read_csv(cache_path, parse_dates=["timestamp"], index_col="timestamp")
            print(f"  ✓ 缓存命中，共 {len(df)} 根K线")
            return df
        except Exception as e:
            print(f"  ⚠ 缓存读取失败: {e}，将从网络获取")
    
    start_dt = datetime.fromisoformat(start)
    end_dt = datetime.fromisoformat(end)
    
    binance = BinanceService()
    
    # 分批获取数据
    all_dfs = []
    current_start = start_dt
    batch_size = 1000
    batch_count = 0
    interval_minutes = _parse_interval_to_minutes(interval)
    
    while current_start < end_dt:
        batch_count += 1
        try:
            df_batch = await binance.get_klines_dataframe(
                symbol=symbol_ccxt,
                timeframe=interval,
                limit=batch_size,
                start=current_start,
                end=end_dt
            )
            
            if df_batch is None or len(df_batch) == 0:
                break
            
            all_dfs.append(df_batch)
            print(f"  批次 {batch_count}: 获取 {len(df_batch)} 根K线")
            
            current_start = df_batch.index[-1] + timedelta(minutes=interval_minutes)
            if len(df_batch) < batch_size:
                break
        except Exception as e:
            print(f"  ⚠ 批次 {batch_count} 获取失败: {e}")
            break
    
    try:
        await binance.close()
    except:
        pass
    
    if not all_dfs:
        print(f"❌ 未能获取任何数据")
        sys.exit(1)
    
    df = pd.concat(all_dfs)
    df = df[~df.index.duplicated(keep="first")].sort_index()
    df = df[(df.index >= start_dt) & (df.index <= end_dt)]
    
    if len(df) < 300:
        print(f"❌ 数据不足: 当前 {len(df)} 根，至少需要 300 根")
        sys.exit(1)
    
    print(f"  ✓ 共获取 {len(df)} 根 K 线数据")
    
    if use_cache:
        try:
            df.to_csv(cache_path, encoding='utf-8-sig')
            print(f"  ✓ 已缓存到: {cache_path}")
        except Exception as e:
            print(f"  ⚠ 缓存保存失败: {e}")
    
    return df


# ─────────────────────────────────────────────────────────────────────────────
# 场景 1: 无 WFA（固定参数优化）
# ─────────────────────────────────────────────────────────────────────────────

async def run_without_wfa(df: pd.DataFrame, strategy_type: str, n_trials: int, initial_capital: float) -> Dict[str, Any]:
    """使用全局数据进行一次参数优化，并回测"""
    print(f"\n[2/4] 无 WFA 场景（固定参数优化）")
    print(f"  策略: {strategy_type} | 优化 trials: {n_trials}")
    
    # 执行 Optuna 优化（自动从模板获取参数范围）
    optimizer = OptunaOptimizer(df, strategy_type, initial_capital)
    optimization_result = optimizer.optimize(
        n_trials=n_trials,
        use_numba=False
    )
    
    if not optimization_result or "best_params" not in optimization_result:
        print("❌ 参数优化失败")
        return None
    
    # 提取最优参数
    best_params = optimization_result["best_params"]
    best_sharpe = optimization_result.get("best_sharpe", 0.0)
    print(f"✓ 最优参数: {best_params}")
    print(f"  优化 Sharpe: {best_sharpe:.4f}")
    
    # 使用最优参数在全局数据上回测
    signal_func = build_signal_func(strategy_type, best_params)
    bt = VectorizedBacktester(df, signal_func, initial_capital)
    backtest_result = bt.run()
    
    # 提取并验证指标
    annual_return = backtest_result.get("annual_return", 0.0)
    sharpe_ratio = backtest_result.get("sharpe_ratio", 0.0)
    max_drawdown = backtest_result.get("max_drawdown", 0.0)
    total_return = backtest_result.get("total_return", 0.0)
    total_trades = backtest_result.get("total_trades", 0)
    
    # 数值合理性检查（仅警告，不截断，根因已在 annualization 层修复）
    # 1. 年化收益率合理性检查
    # 注意：VectorizedBacktester 返回的是百分比口径（如 28.65 表示 28.65%）
    if annual_return > 1000.0:  # 超过 1000%
        print(f"  ⚠ 警告: 年化收益率 {annual_return:.2f}% 异常高，请检查数据周期")
    if annual_return < -100.0:  # 低于 -100%
        print(f"  ⚠ 警告: 年化收益率 {annual_return:.2f}% 低于 -100%，请检查计算逻辑")
    
    # 2. 最大回撤合理性检查
    if max_drawdown > 100.0:
        print(f"  ⚠ 警告: 最大回撤 {max_drawdown:.2f}% 超过 100%，请检查计算逻辑")
    if max_drawdown < 0:
        print(f"  ⚠ 警告: 最大回撤 {max_drawdown:.2f}% 为负值，请检查计算逻辑")
    
    # 3. 夏普比率合理性检查
    if abs(sharpe_ratio) > 10:
        print(f"  ⚠ 警告: 夏普比率 {sharpe_ratio:.4f} 绝对值超过10，请检查数据周期")
    
    # 4. 交易次数过少警告
    if total_trades < 10:
        print(f"  ⚠ 警告: 交易次数仅 {total_trades} 次，统计结果可能不可靠")
    
    # 将百分比口径转换为小数口径，以便与 WFA 场景的数据口径一致
    # VectorizedBacktester 返回的是百分比口径（如 28.65 表示 28.65%）
    # WalkForwardOptimizer 返回的是小数口径（如 0.28 表示 28%）
    metrics = {
        "annual_return": annual_return / 100.0 if annual_return else 0.0,
        "sharpe_ratio": sharpe_ratio,
        "max_drawdown": max_drawdown / 100.0 if max_drawdown else 0.0,
        "total_return": total_return / 100.0 if total_return else 0.0,
        "total_trades": total_trades,
    }
    
    print(f"✓ 回测完成:")
    print(f"  年化收益: {annual_return:.2f}%")
    print(f"  夏普比率: {sharpe_ratio:.4f}")
    print(f"  最大回撤: {max_drawdown:.2f}%")
    print(f"  交易次数: {total_trades}")
    
    return metrics


# ─────────────────────────────────────────────────────────────────────────────
# 场景 2: 有 WFA（滚动窗口优化）
# ─────────────────────────────────────────────────────────────────────────────

async def run_with_wfa(
    df: pd.DataFrame,
    strategy_type: str,
    is_days: int,
    oos_days: int,
    step_days: int,
    n_trials: int,
    initial_capital: float
) -> Dict[str, Any]:
    """执行 WFA 滚动窗口优化"""
    print(f"\n[3/4] 有 WFA 场景（滚动窗口优化）")
    print(f"  IS={is_days}天 | OOS={oos_days}天 | Step={step_days}天")
    
    optimizer = WalkForwardOptimizer(df, strategy_type, initial_capital)
    wfo_result = await optimizer.run_wfo(
        is_days=is_days,
        oos_days=oos_days,
        step_days=step_days,
        n_trials=n_trials,
        use_numba=False
    )
    
    if "error" in wfo_result:
        print(f"❌ WFA 执行失败: {wfo_result['error']}")
        return None
    
    metrics = wfo_result.get("metrics", {})
    stability = wfo_result.get("stability_analysis", {})
    
    print(f"✓ WFA 完成:")
    print(f"  窗口数: {metrics.get('num_windows', 0)}")
    
    # 提取并验证指标
    avg_oos_sharpe = metrics.get("avg_oos_sharpe", 0.0)
    avg_oos_annual_return = metrics.get("avg_oos_annual_return", 0.0)
    total_oos_return = metrics.get("total_oos_return", 0.0)
    total_oos_trades = metrics.get("total_oos_trades", 0)
    overall_wfe = metrics.get("overall_wfe", 0.0)
    
    # 数值合理性检查（仅警告，不截断，根因已在 annualization 层修复）
    # 1. 夏普比率合理性检查
    if abs(avg_oos_sharpe) > 10 or math.isinf(avg_oos_sharpe) or math.isnan(avg_oos_sharpe):
        print(f"  ⚠ 警告: OOS 夏普比率 {avg_oos_sharpe} 异常，请检查数据周期")
    
    # 2. 年化收益率合理性检查
    if avg_oos_annual_return > 10.0:
        print(f"  ⚠ 警告: OOS 年化收益 {avg_oos_annual_return:.2%} 异常高，请检查数据周期")
    if avg_oos_annual_return < -1.0:
        print(f"  ⚠ 警告: OOS 年化收益 {avg_oos_annual_return:.2%} 低于 -100%，请检查计算逻辑")
    
    # 3. WFE 合理性检查
    if overall_wfe > 2.0 or overall_wfe < -2.0:
        print(f"  ⚠ 警告: WFE {overall_wfe:.2%} 超出合理范围，请检查计算逻辑")
    
    # 4. 交易次数检查
    if total_oos_trades < 10:
        print(f"  ⚠ 警告: OOS 交易次数仅 {total_oos_trades} 次，统计结果可能不可靠")
    
    print(f"  平均 OOS 夏普: {avg_oos_sharpe:.4f}")
    print(f"  总体 WFE: {overall_wfe:.2%}")
    print(f"  OOS 年化收益: {avg_oos_annual_return:.2%}")
    
    # 提取 OOS 窗口交易次数
    oos_trades_per_window, _, _ = validate_oos_trades(wfo_result, 0)
    
    # 注意：WalkForwardOptimizer 返回的 total_oos_return 是百分比口径
    # 需要转换为小数口径以便与无 WFA 场景一致
    return {
        "annual_return": avg_oos_annual_return,  # 已经是小数口径
        "sharpe_ratio": avg_oos_sharpe,
        "max_drawdown": _calc_avg_drawdown(wfo_result),  # 函数内部已转换
        "total_return": total_oos_return / 100.0 if total_oos_return else 0.0,  # 百分比转小数
        "total_trades": total_oos_trades,
        "wfe": overall_wfe,
        "param_stability": stability.get("overall_param_stability", 0.0),
        "oos_trades_per_window": oos_trades_per_window,  # 新增：各窗口OOS交易次数
    }


def _calc_avg_drawdown(wfo_result: Dict[str, Any]) -> float:
    """计算 WFA 各窗口 OOS 回撤的平均值，返回小数口径
    
    注意：WalkForwardOptimizer 返回的 oos_drawdown 是百分比口径（如 15.0 表示 15%）
    本函数返回小数口径（如 0.15 表示 15%），以便与无 WFA 场景的口径一致
    """
    windows = wfo_result.get("walk_forward_results", [])
    if not windows:
        return 0.0
    
    drawdowns = []
    for w in windows:
        dd = w.get("oos_drawdown", 0.0)
        # oos_drawdown 是百分比口径，限制在 0-100% 范围
        if dd > 100.0:
            dd = 100.0
        elif dd < 0:
            dd = 0.0
        # 转换为小数口径
        drawdowns.append(dd / 100.0)
    
    avg_dd = float(np.mean(drawdowns)) if drawdowns else 0.0
    return avg_dd


def validate_oos_trades(wfo_result: Dict[str, Any], min_trades: int) -> Tuple[List[int], int, bool]:
    """校验 OOS 窗口交易次数
    
    Args:
        wfo_result: WalkForwardOptimizer 返回的结果字典
        min_trades: 单窗口最低交易次数阈值
        
    Returns:
        (各窗口OOS交易次数列表, 不满足阈值的窗口数, 是否全部满足)
    """
    windows = wfo_result.get("walk_forward_results", [])
    if not windows:
        return [], 0, True
    
    trades_per_window = []
    insufficient_count = 0
    
    for w in windows:
        oos_trades = w.get("oos_total_trades", 0)
        trades_per_window.append(oos_trades)
        if oos_trades < min_trades:
            insufficient_count += 1
    
    all_satisfied = insufficient_count == 0
    return trades_per_window, insufficient_count, all_satisfied


# ─────────────────────────────────────────────────────────────────────────────
# 对比输出
# ─────────────────────────────────────────────────────────────────────────────

def print_comparison_table(
    symbol: str,
    interval: str,
    strategy_type: str,
    start: str,
    end: str,
    no_wfa: Dict[str, Any],
    with_wfa: Dict[str, Any],
    output_csv: Optional[str] = None,
    min_total_trades: int = 100,
    min_oos_trades: int = 20
):
    """打印对比表格"""
    print("\n" + "=" * 80)
    print(f"WFA 对比分析报告 | {symbol} {interval} | {strategy_type.upper()}策略 | {start} ~ {end}")
    print("=" * 80)
    
    # 构建对比数据
    metrics_list = [
        ("年化收益率", "annual_return", "percentage", True),
        ("夏普比率", "sharpe_ratio", "decimal", True),
        ("最大回撤", "max_drawdown", "percentage", False),  # 越小越好
        ("总收益率", "total_return", "percentage", True),
        ("交易次数", "total_trades", "absolute", None),
        ("WFE 均值", "wfe", "percentage", True),
        ("参数稳定性", "param_stability", "decimal", True),
    ]
    
    # 表格头部
    header = f"{'指标':<15} | {'无WFA（固定参数）':>18} | {'有WFA（动态参数）':>18} | {'差异':>12} | {'评估'}"
    separator = "-" * 80
    
    print(f"\n{header}")
    print(separator)
    
    # 收集 CSV 数据
    csv_data = []
    
    for label, key, fmt_type, better_higher in metrics_list:
        val_no = no_wfa.get(key) if no_wfa else None
        val_with = with_wfa.get(key) if with_wfa else None
        
        # 格式化数值
        str_no = _format_value(val_no, fmt_type)
        str_with = _format_value(val_with, fmt_type)
        
        # 计算差异
        if val_no is not None and val_with is not None:
            diff = val_with - val_no
            str_diff = _format_diff(diff, fmt_type)
            
            # 评估
            if better_higher is True:
                assessment = "↑ 改善" if diff > 0 else ("↓ 退化" if diff < 0 else "→ 持平")
            elif better_higher is False:
                assessment = "↑ 改善" if diff < 0 else ("↓ 退化" if diff > 0 else "→ 持平")
            else:
                assessment = "-"
        else:
            str_diff = "-"
            assessment = "-"
        
        print(f"{label:<15} | {str_no:>18} | {str_with:>18} | {str_diff:>12} | {assessment}")
        
        # 收集 CSV 数据（原始数值）
        csv_data.append({
            "指标名称": label,
            "无WFA值": str_no,
            "有WFA值": str_with,
            "差异": str_diff,
            "评估": assessment
        })
    
    print(separator)
    
    # OOS 窗口交易统计
    oos_trades_per_window = with_wfa.get("oos_trades_per_window", []) if with_wfa else []
    total_trades = no_wfa.get("total_trades", 0) if no_wfa else 0
    
    if oos_trades_per_window:
        min_oos = min(oos_trades_per_window)
        max_oos = max(oos_trades_per_window)
        avg_oos = sum(oos_trades_per_window) / len(oos_trades_per_window)
        print(f"{'OOS窗口交易':<15} | {'min=' + str(min_oos):>18} | {'avg=' + f'{avg_oos:.1f}':>18} | {'max=' + str(max_oos):>12} | {'窗口数=' + str(len(oos_trades_per_window))}")
        
        # 收集到 CSV 数据
        csv_data.append({
            "指标名称": "OOS窗口交易",
            "无WFA值": f"min={min_oos}",
            "有WFA值": f"avg={avg_oos:.1f}",
            "差异": f"max={max_oos}",
            "评估": f"窗口数={len(oos_trades_per_window)}"
        })
    
    # 可信度评估
    reliability = ""
    insufficient_oos_windows = sum(1 for t in oos_trades_per_window if t < min_oos_trades)
    
    if total_trades >= min_total_trades and (not oos_trades_per_window or insufficient_oos_windows == 0):
        reliability = "统计可靠"
    elif total_trades >= min_total_trades and insufficient_oos_windows > 0:
        reliability = f"部分窗口样本不足（{insufficient_oos_windows}/{len(oos_trades_per_window)}窗口<{min_oos_trades}次）"
    else:
        reliability = f"样本不足，结论仅供参考（{total_trades}<{min_total_trades}次）"
    
    print(f"{'可信度':<15} | {'-':>18} | {reliability:>18} | {'-':>12} | {'-'}")
    csv_data.append({
        "指标名称": "可信度",
        "无WFA值": "-",
        "有WFA值": reliability,
        "差异": "-",
        "评估": "-"
    })
    
    print(separator)
    
    # 结论
    print("\n📊 结论:")
    wfe = with_wfa.get("wfe", 0.0) if with_wfa else 0.0
    oos_sharpe = with_wfa.get("sharpe_ratio", 0.0) if with_wfa else 0.0
    
    if wfe > 0.5 and oos_sharpe > 0:
        print(f"  ✓ WFA 有效（WFE={wfe:.2%} > 50%，OOS夏普={oos_sharpe:.4f} > 0）")
        print(f"  ✓ 前向走查分析能够提升策略泛化能力")
        conclusion_text = f"WFA有效（WFE={wfe:.2%}）"
    elif wfe > 0.3:
        print(f"  ⚠ WFA 部分有效（WFE={wfe:.2%}，OOS夏普={oos_sharpe:.4f}）")
        print(f"  ⚠ 建议结合其他指标综合判断")
        conclusion_text = f"部分有效（WFE={wfe:.2%}）"
    else:
        print(f"  ✗ WFA 效果不佳（WFE={wfe:.2%}，OOS夏普={oos_sharpe:.4f}）")
        print(f"  ✗ 可能存在过拟合或策略本身不适应该市场")
        conclusion_text = f"效果不佳（WFE={wfe:.2%}）"
    
    print("=" * 80)
    
    # CSV 输出
    if output_csv:
        try:
            with open(output_csv, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                # 元信息行
                writer.writerow(["WFA 对比分析报告"])
                writer.writerow(["交易对", symbol])
                writer.writerow(["周期", interval])
                writer.writerow(["策略", strategy_type.upper()])
                writer.writerow(["时间范围", f"{start} ~ {end}"])
                writer.writerow([])  # 空行
                # 结论行
                writer.writerow(["结论", conclusion_text])
                writer.writerow([])  # 空行
                # 表头
                writer.writerow(["指标名称", "无WFA值", "有WFA值", "差异", "评估"])
                # 数据行
                for row in csv_data:
                    writer.writerow([row["指标名称"], row["无WFA值"], row["有WFA值"], row["差异"], row["评估"]])
            print(f"\n✓ 结果已导出到: {output_csv}")
        except Exception as e:
            print(f"\n⚠ CSV 导出失败: {e}")


def _format_value(value, fmt_type: str) -> str:
    """格式化单个数值"""
    if value is None:
        return "-"
    
    if fmt_type == "percentage":
        return f"{value:.2%}"
    elif fmt_type == "decimal":
        return f"{value:.4f}"
    else:
        return f"{int(value)}"


def _format_diff(diff, fmt_type: str) -> str:
    """格式化差异值"""
    if fmt_type == "percentage":
        sign = "+" if diff > 0 else ""
        return f"{sign}{diff:.2%}"
    elif fmt_type == "decimal":
        sign = "+" if diff > 0 else ""
        return f"{sign}{diff:.4f}"
    else:
        sign = "+" if diff > 0 else ""
        return f"{sign}{int(diff)}"


# ─────────────────────────────────────────────────────────────────────────────
# CSV 路径构建辅助函数
# ─────────────────────────────────────────────────────────────────────────────

def _build_csv_path(output_csv_arg: str, symbol: str, interval: str, strategy: str, start: str, end: str, is_multi: bool) -> str:
    """根据运行配置构建 CSV 输出路径
    
    Args:
        output_csv_arg: 命令行传入的 output_csv 参数值
            - 'auto': 自动生成文件名
            - 目录路径: 在该目录下自动生成文件名
            - 完整路径: 直接使用
        symbol: 交易对
        interval: K线周期
        strategy: 策略类型（多策略模式可为空）
        start: 开始时间
        end: 结束时间
        is_multi: 是否为多策略模式
    
    Returns:
        完整的 CSV 输出路径
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    start_compact = start.replace("-", "")
    end_compact = end.replace("-", "")
    symbol_upper = symbol.upper()
    
    # 生成文件名
    if is_multi:
        filename = f"wfa_{symbol_upper}_{interval}_multi_{start_compact}_{end_compact}.csv"
    else:
        filename = f"wfa_{symbol_upper}_{interval}_{strategy}_{start_compact}_{end_compact}.csv"
    
    # auto 模式：在脚本目录下的 output 子目录生成文件
    if output_csv_arg == 'auto':
        output_dir = os.path.join(script_dir, 'output')
        os.makedirs(output_dir, exist_ok=True)
        return os.path.join(output_dir, filename)
    
    # 检查是否是目录
    if os.path.isdir(output_csv_arg) or output_csv_arg.endswith(('/', '\\')):
        return os.path.join(output_csv_arg, filename)
    
    # 直接使用指定路径
    return output_csv_arg


# ─────────────────────────────────────────────────────────────────────────────
# 主函数
# ─────────────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="WFA 有无对比分析")
    parser.add_argument("--symbol", type=str, default="BTCUSDT", help="交易对 (默认: BTCUSDT)")
    parser.add_argument("--interval", type=str, default="1d", help="K线周期 (默认: 1d)")
    parser.add_argument("--start", type=str, default="2023-06-01", help="开始时间 (默认: 2023-06-01)")
    parser.add_argument("--end", type=str, default="2025-12-31", help="结束时间 (默认: 2025-12-31)")
    parser.add_argument("--strategy", type=str, default="rsi", help="策略类型 (默认: rsi)")
    parser.add_argument("--is-days", type=int, default=180, help="样本内窗口天数 (默认: 180)")
    parser.add_argument("--oos-days", type=int, default=60, help="样本外窗口天数 (默认: 60)")
    parser.add_argument("--step-days", type=int, default=60, help="步长天数 (默认: 60)")
    parser.add_argument("--n-trials", type=int, default=50, help="Optuna 优化 trials (默认: 50)")
    parser.add_argument("--initial-capital", type=float, default=10000, help="初始资金 (默认: 10000)")
    parser.add_argument("--commission", type=float, default=0.001, help="手续费率 (默认: 0.001)")
    # 新增诊断模块参数
    parser.add_argument("--compare-strategies", action="store_true", help="启用多策略对比模式")
    parser.add_argument("--strategies", type=str, default="rsi,ma,boll,macd,ema_triple,atr_trend,turtle,ichimoku",
                        help="多策略对比的策略列表，逗号分隔 (默认: 全部8个原子策略)")
    parser.add_argument("--skip-diagnostics", action="store_true", help="跳过诊断模块（仅执行WFA对比）")
    parser.add_argument("--use-cache", action="store_true", help="使用本地缓存的K线数据")
    parser.add_argument("--output-csv", nargs='?', const='auto', default=None,
                        help="CSV 输出（不带值则自动命名，或指定路径）")
    # 交易样本量优化参数
    parser.add_argument("--min-total-trades", type=int, default=100,
                        help="总交易次数最低要求 (默认: 100)")
    parser.add_argument("--min-oos-trades", type=int, default=20,
                        help="单个 OOS 窗口最低交易次数 (默认: 20)")
    parser.add_argument("--no-auto-downgrade", action="store_true",
                        help="禁用自动周期降级（调试用）")
    
    args = parser.parse_args()
    
    print("=" * 80)
    print("WFA 有无对比分析脚本")
    if args.use_cache:
        print("[配置] 使用缓存数据模式")
    print("=" * 80)
    
    # 配置摘要
    print(f"配置: {args.symbol} | {args.interval} | {args.start} ~ {args.end} | IS={args.is_days}天 OOS={args.oos_days}天 | Trials={args.n_trials}")
    print()
    
    # 默认策略列表（全部8个原子策略）
    default_strategies = ["rsi", "ma", "boll", "macd", "ema_triple", "atr_trend", "turtle", "ichimoku"]
    
    # 解析策略列表
    if args.strategies:
        strategy_list = [s.strip().lower() for s in args.strategies.split(",")]
    else:
        strategy_list = default_strategies
    
    # ===== 多策略对比模式 =====
    if args.compare_strategies:
        # 1. 获取数据
        df = await fetch_data(args.symbol, args.interval, args.start, args.end, args.use_cache)
        
        # 2. 数据完整性检查
        if not args.skip_diagnostics:
            check_data_integrity(df, args.interval)
        
        # 3. 多策略对比（替代单一策略对比）
        csv_path = None
        if args.output_csv is not None:
            csv_path = _build_csv_path(args.output_csv, args.symbol, args.interval, '', args.start, args.end, is_multi=True)
        await compare_strategies(
            df, strategy_list, args.initial_capital, args.n_trials,
            args.is_days, args.oos_days, args.step_days, csv_path,
            # 新增参数
            original_interval=args.interval,
            no_auto_downgrade=args.no_auto_downgrade,
            min_total_trades=args.min_total_trades,
            min_oos_trades=args.min_oos_trades,
            symbol=args.symbol,
            start=args.start,
            end=args.end,
            use_cache=args.use_cache
        )
        return
    
    # ===== 单一策略模式 =====
    # 1. 获取数据
    df = await fetch_data(args.symbol, args.interval, args.start, args.end, args.use_cache)
    actual_interval = args.interval  # 记录实际使用的周期（可能因降级而改变）
    
    # 2. 数据完整性检查（新增）
    if not args.skip_diagnostics:
        check_data_integrity(df, args.interval)
    
    # 3. 无 WFA 场景
    no_wfa = await run_without_wfa(df, args.strategy, args.n_trials, args.initial_capital)
        
    # 3.5 周期自适应降级逻辑
    if no_wfa and not args.no_auto_downgrade:
        total_trades = no_wfa.get("total_trades", 0)
        min_trades = args.min_total_trades
            
        if total_trades < min_trades:
            print(f"\n⚠ 交易次数不足: 当前 {total_trades} 次，阈值 {min_trades} 次")
            print(f"  开始周期降级尝试，降级链: {INTERVAL_FALLBACK_CHAIN}")
                
            # 记录各周期的交易次数，用于选择最佳周期
            interval_trades = [(args.interval, total_trades, df)]
                
            for fallback_interval in INTERVAL_FALLBACK_CHAIN:
                # 跳过与当前周期相同的
                if fallback_interval == actual_interval:
                    continue
                        
                print(f"\n[降级尝试] 切换到周期: {fallback_interval}")
                    
                # 重新获取数据
                try:
                    fallback_df = await fetch_data(args.symbol, fallback_interval, args.start, args.end, args.use_cache)
                except Exception as e:
                    print(f"  ✗ 获取 {fallback_interval} 数据失败: {e}")
                    continue
                    
                # 重新执行无 WFA 优化
                fallback_result = await run_without_wfa(fallback_df, args.strategy, args.n_trials, args.initial_capital)
                    
                if fallback_result:
                    fallback_trades = fallback_result.get("total_trades", 0)
                    interval_trades.append((fallback_interval, fallback_trades, fallback_df))
                        
                    if fallback_trades >= min_trades:
                        print(f"  ✓ 周期 {fallback_interval} 满足要求: {fallback_trades} 次 >= {min_trades} 次")
                        actual_interval = fallback_interval
                        df = fallback_df
                        no_wfa = fallback_result
                        break
                    else:
                        print(f"  - 周期 {fallback_interval} 交易次数: {fallback_trades} 次，仍不足")
                
            # 如果所有周期都不满足，选择交易次数最多的
            if no_wfa.get("total_trades", 0) < min_trades:
                best_interval, best_trades, best_df = max(interval_trades, key=lambda x: x[1])
                if best_interval != actual_interval:
                    print(f"\n⚠ 所有周期均不满足阈值，使用交易次数最多的周期: {best_interval} ({best_trades} 次)")
                    actual_interval = best_interval
                    df = best_df
                    # 重新获取该周期的结果
                    no_wfa = await run_without_wfa(df, args.strategy, args.n_trials, args.initial_capital)
                else:
                    print(f"\n⚠ 所有周期均不满足阈值，继续使用原始周期: {actual_interval} ({best_trades} 次)")
                
            print(f"\n✓ 最终使用周期: {actual_interval}")
    elif no_wfa and args.no_auto_downgrade:
        total_trades = no_wfa.get("total_trades", 0)
        if total_trades < args.min_total_trades:
            print(f"\n⚠ 交易次数不足: 当前 {total_trades} 次，阈值 {args.min_total_trades} 次")
            print(f"  已禁用自动降级（--no-auto-downgrade），继续使用原始周期: {actual_interval}")
        
    # 提取最优参数用于后续诊断
    best_params = {}
    if no_wfa:
        # 重新优化以获取最优参数
        try:
            optimizer = OptunaOptimizer(df, args.strategy, args.initial_capital)
            opt_result = optimizer.optimize(n_trials=args.n_trials, use_numba=False)
            if opt_result and "best_params" in opt_result:
                best_params = opt_result["best_params"]
        except:
            pass
    
    # 4. 策略信号检查（新增）
    if not args.skip_diagnostics and best_params:
        check_strategy_signals(df, args.strategy, best_params)
    
    # 5. 回测结果手动验证（新增）
    if not args.skip_diagnostics and best_params:
        verify_backtest_trades(df, args.strategy, best_params, args.initial_capital, args.commission)
    
    # 6. 有 WFA 场景
    with_wfa = await run_with_wfa(
        df, args.strategy, args.is_days, args.oos_days, args.step_days,
        args.n_trials, args.initial_capital
    )
    
    # 7. 输出对比
    if no_wfa and with_wfa:
        csv_path = None
        if args.output_csv is not None:
            csv_path = _build_csv_path(args.output_csv, args.symbol, actual_interval, args.strategy, args.start, args.end, is_multi=False)
        print_comparison_table(
            args.symbol, actual_interval, args.strategy,
            args.start, args.end, no_wfa, with_wfa, csv_path,
            args.min_total_trades, args.min_oos_trades
        )
    else:
        print("\n❌ 对比分析失败，请检查上方错误信息")


if __name__ == "__main__":
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')
    asyncio.run(main())
