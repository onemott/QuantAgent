import logging
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from sqlalchemy import select, func
from app.services.database import get_db
from app.models.db_models import PaperTrade, BacktestResult, EquitySnapshot, ReplaySession

logger = logging.getLogger(__name__)

# Strategy mapping for attribution lookup
STRATEGY_MAP = {
    "auto_trend_ma": "ma",
    "auto_reversion_rsi": "rsi",
    "auto_volatility_boll": "boll"
}

class AttributionService:
    """
    QAD (Quant Attribution & Dissection) 差异归因框架实现。
    基于订单级对齐实现回测与模拟盘的收益差异分解。
    """

    def aggregate_executions(self, df_exec: pd.DataFrame, prefix: str) -> pd.DataFrame:
        """
        聚合成交表：1个信号对应多笔成交时，合并为1行。
        prefix: 'bt' or 'sim'
        """
        if df_exec.empty:
            return pd.DataFrame(columns=['signal_id', f'{prefix}_qty', f'{prefix}_price', f'{prefix}_fee', f'{prefix}_exec_ts'])

        agg_dict = {
            'exec_qty': 'sum',
            'exec_price': lambda x: np.average(x, weights=df_exec.loc[x.index, 'exec_qty']) if sum(df_exec.loc[x.index, 'exec_qty']) > 0 else 0.0,
            'fee': 'sum',
            'exec_ts': 'max'
        }
        
        df_agg = df_exec.groupby('signal_id').agg(agg_dict).reset_index()
        
        # 重命名
        df_agg.columns = ['signal_id', f'{prefix}_qty', f'{prefix}_price', f'{prefix}_fee', f'{prefix}_exec_ts']
        return df_agg

    def merge_data(
        self,
        df_signals: pd.DataFrame,
        df_bt_agg: pd.DataFrame,
        df_sim_agg: pd.DataFrame
    ) -> pd.DataFrame:
        """
        合并信号表与聚合后的回测/模拟盘表，生成宽表
        """
        # 以信号表为主表
        df_combined = df_signals.merge(df_bt_agg, on='signal_id', how='left')
        df_combined = df_combined.merge(df_sim_agg, on='signal_id', how='left')
        
        # 填充缺失值
        cols_to_fill_zero = ['bt_qty', 'bt_price', 'bt_fee', 'sim_qty', 'sim_price', 'sim_fee']
        for col in cols_to_fill_zero:
            if col in df_combined.columns:
                df_combined[col] = df_combined[col].fillna(0.0)
            else:
                df_combined[col] = 0.0
                
        return df_combined

    def calculate_attribution(
        self,
        df_combined: pd.DataFrame,
        df_mkt: Optional[pd.DataFrame] = None
    ) -> pd.DataFrame:
        """
        核心归因计算函数 - 增强版
        包含：delta_price, delta_fill, delta_timing, delta_fees, 
              slippage_impact, latency_impact, execution_quality, timing_diff
        """
        df = df_combined.copy()
        
        # 3.1 共同成交量与数量差
        df['q_common'] = df[['bt_qty', 'sim_qty']].min(axis=1)
        df['q_diff'] = df['sim_qty'] - df['bt_qty']
        
        # 3.2 价格差异 (Delta_Price)
        # 公式：Delta_Price = (sim_price - bt_price) * Q_common * direction
        df['delta_price'] = (df['sim_price'] - df['bt_price']) * df['q_common'] * df['direction']
        
        # 3.3 成交率差异 (Delta_Fill)
        # 公式：Delta_Fill = Q_diff * bt_price * direction
        df['delta_fill'] = df['q_diff'] * df['bt_price'] * df['direction']
        
        # 3.4 时机差异 (Delta_Timing) - 暂设为0，除非接入基准行情
        df['delta_timing'] = 0.0
        if df_mkt is not None and not df_mkt.empty and 'sim_exec_ts' in df.columns:
            # TODO: 实现插值逻辑以支持时机差异
            pass
            
        # 3.5 手续费差异 (Delta_Fees)
        # 公式：Delta_Fees = bt_fee - sim_fee
        df['delta_fees'] = df['bt_fee'] - df['sim_fee']
        
        # 3.6 新增归因维度 - Slippage Impact
        # slippage_impact = (实际成交价 - 理想价格/触发价) * 成交量 * direction
        # 对于买入：正值表示多花钱（不利滑点），负值表示省钱
        # 对于卖出：direction=-1，正值表示少收钱（不利滑点）
        df['slippage_impact'] = (df['sim_price'] - df['trigger_price']) * df['sim_qty'] * df['direction']
        
        # 3.7 新增归因维度 - Timing Diff (信号产生到成交的时间差，秒)
        df['timing_diff'] = 0.0
        if 'sim_exec_ts' in df.columns and 'timestamp' in df.columns:
            df['timing_diff'] = df.apply(
                lambda row: self._calc_timing_diff(row.get('timestamp'), row.get('sim_exec_ts')),
                axis=1
            )
        
        # 3.8 新增归因维度 - Latency Impact
        # 延迟导致的价格变化影响 = timing_diff * 预估每秒价格变化率 * qty * direction
        # 简化计算：使用 slippage 作为延迟影响的代理指标
        # latency_impact ≈ abs(slippage_impact) 如果 timing_diff > 0
        df['latency_impact'] = df.apply(
            lambda row: abs(row['slippage_impact']) if row['timing_diff'] > 0 else 0.0,
            axis=1
        )
        
        # 3.9 新增归因维度 - Execution Quality (0-100分)
        # 基于滑点和延迟综合评估
        # 评分标准：滑点百分比 < 0.1% 得100分，每增加0.1%减10分，最低0分
        df['execution_quality'] = df.apply(
            lambda row: self._calc_execution_quality(
                row['sim_price'], row['trigger_price'], row['timing_diff']
            ),
            axis=1
        )
        
        # 3.10 总差异校验
        df['delta_total'] = df['delta_price'] + df['delta_fill'] + df['delta_timing'] + df['delta_fees']
        
        return df
    
    def _calc_timing_diff(self, signal_ts: Any, exec_ts: Any) -> float:
        """计算信号时间到成交时间的差值（秒）"""
        try:
            if signal_ts is None or exec_ts is None:
                return 0.0
            if isinstance(signal_ts, str):
                signal_ts = pd.to_datetime(signal_ts)
            if isinstance(exec_ts, str):
                exec_ts = pd.to_datetime(exec_ts)
            diff = (exec_ts - signal_ts).total_seconds()
            return max(0.0, diff)  # 只返回正值
        except Exception:
            return 0.0
    
    def _calc_execution_quality(
        self, exec_price: float, ideal_price: float, timing_diff: float
    ) -> float:
        """计算执行质量评分 (0-100)
        
        评分维度：
        1. 滑点百分比：< 0.1% 得100分，每增加0.1%减10分
        2. 延迟惩罚：每延迟1秒减1分
        """
        if ideal_price <= 0:
            return 50.0  # 缺少基准价时返回中间分数
        
        # 滑点百分比（绝对值）
        slippage_pct = abs(exec_price - ideal_price) / ideal_price * 100
        
        # 滑点评分（滑点百分比每0.1%减10分）
        slippage_score = max(0, 100 - (slippage_pct / 0.1) * 10)
        
        # 延迟惩罚（每秒减1分）
        latency_penalty = min(timing_diff, 20)  # 最多扣20分
        
        # 综合评分
        final_score = max(0, slippage_score - latency_penalty)
        return round(final_score, 1)

    def aggregate_results(self, df_attribution: pd.DataFrame) -> Dict[str, Any]:
        """
        结果聚合函数：按日、按品种、全局
        包含新增的归因维度统计
        """
        if df_attribution.empty:
            return {
                "daily": [],
                "symbol": [],
                "global": {
                    "delta_price": 0.0,
                    "delta_fill": 0.0,
                    "delta_timing": 0.0,
                    "delta_fees": 0.0,
                    "delta_total": 0.0,
                    "total_slippage_impact": 0.0,
                    "total_latency_impact": 0.0,
                    "avg_execution_quality": None,
                    "avg_timing_diff": None,
                }
            }
            
        # 确保 timestamp 为 datetime 类型
        df_attribution['timestamp'] = pd.to_datetime(df_attribution['timestamp'])
        df_attribution['date'] = df_attribution['timestamp'].dt.date
        
        # 原有差异列
        diff_cols = ['delta_price', 'delta_fill', 'delta_timing', 'delta_fees', 'delta_total']
        # 新增归因维度列
        new_cols = ['slippage_impact', 'latency_impact', 'timing_diff', 'execution_quality']
        
        # 按日聚合
        daily_agg = df_attribution.groupby('date')[diff_cols].sum().reset_index()
        daily_agg['date'] = daily_agg['date'].astype(str)
        
        # 按品种聚合
        symbol_agg = df_attribution.groupby('symbol')[diff_cols].sum().reset_index()
        
        # 全局聚合
        global_agg = df_attribution[diff_cols].sum().to_dict()
        
        # Ensure all required keys exist in global_agg
        for col in diff_cols:
            if col not in global_agg:
                global_agg[col] = 0.0
        
        # 新增归因维度的全局汇总
        if 'slippage_impact' in df_attribution.columns:
            global_agg['total_slippage_impact'] = float(df_attribution['slippage_impact'].sum())
        else:
            global_agg['total_slippage_impact'] = 0.0
            
        if 'latency_impact' in df_attribution.columns:
            global_agg['total_latency_impact'] = float(df_attribution['latency_impact'].sum())
        else:
            global_agg['total_latency_impact'] = 0.0
            
        if 'execution_quality' in df_attribution.columns:
            avg_eq = df_attribution['execution_quality'].mean()
            global_agg['avg_execution_quality'] = round(float(avg_eq), 2) if not pd.isna(avg_eq) else None
        else:
            global_agg['avg_execution_quality'] = None
            
        if 'timing_diff' in df_attribution.columns:
            avg_td = df_attribution['timing_diff'].mean()
            global_agg['avg_timing_diff'] = round(float(avg_td), 2) if not pd.isna(avg_td) else None
        else:
            global_agg['avg_timing_diff'] = None
        
        # 计算回测与模拟盘总收益（供瀑布图使用）
        # 回测总收益 = sum((bt_price - trigger_price) * bt_qty * direction - bt_fee)
        bt_pnl = ((df_attribution['bt_price'] - df_attribution['trigger_price']) * 
                  df_attribution['bt_qty'] * df_attribution['direction'] - 
                  df_attribution['bt_fee']).sum()
        
        # 模拟盘总收益 = 回测收益 + 总差异
        sim_pnl = bt_pnl + global_agg.get('delta_total', 0.0)
        
        global_agg['bt_total_pnl'] = bt_pnl
        global_agg['sim_total_pnl'] = sim_pnl
        
        return {
            "daily_agg": daily_agg.to_dict(orient='records'),
            "symbol_agg": symbol_agg.to_dict(orient='records'),
            "global_agg": global_agg,
            # Aliases for compatibility with test scripts
            "daily": daily_agg.to_dict(orient='records'),
            "symbol": symbol_agg.to_dict(orient='records'),
            "global": global_agg
        }

    def _to_python_types(self, obj: Any) -> Any:
        """
        Recursively convert numpy types to standard Python types for JSON/MsgPack serialization.
        """
        if isinstance(obj, dict):
            return {k: self._to_python_types(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._to_python_types(i) for i in obj]
        elif isinstance(obj, (np.integer, np.floating)):
            return obj.item()
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, pd.Timestamp):
            return obj.isoformat()
        elif isinstance(obj, datetime):
            return obj.isoformat()
        return obj

    async def get_strategy_attribution(
        self,
        strategy_id: str,
        symbol: Optional[str] = None,
        days: int = 7,
        base_mode: str = "backtest",
        compare_mode: Optional[str] = None,
        replay_session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        获取策略的归因分析。
        1. 获取信号、回测成交、模拟盘成交。
        2. 运行 QAD 逻辑。
        """
        start_date = datetime.utcnow() - timedelta(days=days)
        
        # Default empty result structure
        empty_result = {
            "daily": [],
            "symbol": [],
            "global": {
                "bt_total_pnl": 0, "sim_total_pnl": 0,
                "delta_price": 0, "delta_fill": 0, "delta_timing": 0, "delta_fees": 0, "delta_total": 0,
                "total_slippage_impact": 0, "total_latency_impact": 0,
                "avg_execution_quality": None, "avg_timing_diff": None,
            },
            "global_agg": {
                "bt_total_pnl": 0, "sim_total_pnl": 0,
                "delta_price": 0, "delta_fill": 0, "delta_timing": 0, "delta_fees": 0, "delta_total": 0,
                "total_slippage_impact": 0, "total_latency_impact": 0,
                "avg_execution_quality": None, "avg_timing_diff": None,
            },
            "daily_agg": [],
            "symbol_agg": [],
            "signal_level_details": [],
            "trades": [],
        }

        try:
            async with get_db() as session:
                # 1. 获取模拟盘/历史回放成交 (PaperTrade)
                # Default to 'paper' if compare_mode is not provided
                comp_mode = compare_mode or "paper"
                stmt_sim = select(PaperTrade).where(
                    PaperTrade.strategy_id == strategy_id,
                    PaperTrade.mode == comp_mode
                )
                
                # 如果提供了 session_id，则按 session_id 过滤
                if replay_session_id:
                    stmt_sim = stmt_sim.where(PaperTrade.session_id == replay_session_id)
                elif comp_mode != "historical_replay":
                    # 非历史回放模式，按时间范围过滤
                    stmt_sim = stmt_sim.where(PaperTrade.created_at >= start_date)
                    
                if symbol:
                    stmt_sim = stmt_sim.where(PaperTrade.symbol == symbol)
                
                result_sim = await session.execute(stmt_sim)
                sim_trades = result_sim.scalars().all()
                
                # 2. 获取回测结果 (BacktestResult)
                # 兼容 auto_xxx_yyy 格式
                bt_type = STRATEGY_MAP.get(strategy_id, strategy_id)
                if bt_type.startswith("auto_") and "_" in bt_type:
                    parts = bt_type.split("_")
                    if len(parts) >= 3:
                        bt_type = parts[-1] # auto_trend_ma -> ma
                
                stmt_bt = select(BacktestResult).where(
                    BacktestResult.strategy_type == bt_type
                ).order_by(BacktestResult.created_at.desc()).limit(1)
                
                result_bt = await session.execute(stmt_bt)
                bt_result = result_bt.scalar_one_or_none()
                
                if not bt_result:
                    logger.warning(f"No backtest result found for strategy={strategy_id}, bt_type={bt_type}")
                    res = empty_result.copy()
                    res["error"] = "No backtest result found for alignment"
                    return res
                    
                # 解析成交数据为 DataFrame
                sim_exec_data = []
                for t in sim_trades:
                    try:
                        sim_exec_data.append({
                            'signal_id': t.client_order_id or f"SIM_{t.id}",
                            'symbol': t.symbol or symbol or "UNKNOWN",
                            'side': t.side or "BUY",
                            'exec_qty': float(t.quantity or 0),
                            'exec_price': float(t.price or 0),
                            'fee': float(t.fee or 0),
                            'exec_ts': t.created_at
                        })
                    except (TypeError, ValueError) as e:
                        logger.warning(f"Failed to parse sim trade {t.id}: {e}")
                        continue
                df_sim_exec = pd.DataFrame(sim_exec_data)
                
                # 从 BacktestResult 解析 bt_exec
                bt_trades = bt_result.trades_summary
                if not bt_trades:
                    logger.warning(f"Backtest result {bt_result.id} has no trades")
                    res = empty_result.copy()
                    res["error"] = "Backtest result has no trades"
                    return res

                bt_exec_data = []
                signal_data = []
                
                for i, bt_t in enumerate(bt_trades):
                    try:
                        # 生成对齐键
                        sig_id = f"SIG_{bt_t.get('entry_time', i)}_{bt_t.get('symbol', symbol or 'UNKNOWN')}"
                        
                        entry_price = float(bt_t.get('entry_price', 0) or 0)
                        quantity = float(bt_t.get('quantity', 0) or 0)
                        fee = float(bt_t.get('fee', 0) or 0)
                        
                        # 回测成交数据
                        bt_exec_data.append({
                            'signal_id': sig_id,
                            'symbol': bt_t.get('symbol', symbol or "UNKNOWN"),
                            'exec_qty': quantity,
                            'exec_price': entry_price,
                            'fee': fee,
                            'exec_ts': pd.to_datetime(bt_t.get('entry_time'))
                        })
                        
                        # 信号表数据 (QAD 核心表)
                        signal_data.append({
                            'signal_id': sig_id,
                            'timestamp': pd.to_datetime(bt_t.get('entry_time')),
                            'symbol': bt_t.get('symbol', symbol or "UNKNOWN"),
                            'direction': 1, # 假设是买入，实际需根据 backtest 逻辑对齐
                            'target_qty': quantity,
                            'trigger_price': entry_price
                        })
                    except (TypeError, ValueError) as e:
                        logger.warning(f"Failed to parse bt trade {i}: {e}")
                        continue
                
                if not bt_exec_data or not signal_data:
                    logger.warning(f"No valid backtest trades parsed for strategy={strategy_id}")
                    res = empty_result.copy()
                    res["error"] = "Failed to parse backtest trades"
                    return res
                
                df_bt_exec = pd.DataFrame(bt_exec_data)
                df_signals = pd.DataFrame(signal_data)
                
                # 3. 对齐模拟盘数据与回测信号
                # 如果 client_order_id 不匹配，使用基于时间和品种的模糊对齐
                if not df_sim_exec.empty:
                    # 尝试通过 signal_id (client_order_id) 直接对齐
                    # 如果没对齐上，尝试模糊对齐
                    unaligned_sim = df_sim_exec[~df_sim_exec['signal_id'].isin(df_signals['signal_id'])]
                    
                    if not unaligned_sim.empty:
                        # 简单模糊对齐：在1分钟时间窗口内寻找最近的信号
                        for idx, sim_row in unaligned_sim.iterrows():
                            try:
                                sim_ts = pd.to_datetime(sim_row['exec_ts'])
                                # 寻找相同品种、时间相差在60秒以内的信号
                                potential_matches = df_signals[
                                    (df_signals['symbol'] == sim_row['symbol']) & 
                                    (abs(df_signals['timestamp'] - sim_ts) < timedelta(seconds=60))
                                ]
                                if not potential_matches.empty:
                                    # 匹配最近的一个
                                    best_match_id = potential_matches.iloc[0]['signal_id']
                                    df_sim_exec.at[idx, 'signal_id'] = best_match_id
                            except Exception as e:
                                logger.debug(f"Failed to align sim trade {idx}: {e}")
                                continue

                # 4. 运行 QAD 计算逻辑
                df_bt_agg = self.aggregate_executions(df_bt_exec, 'bt')
                df_sim_agg = self.aggregate_executions(df_sim_exec, 'sim')
                
                df_combined = self.merge_data(df_signals, df_bt_agg, df_sim_agg)
                df_attribution = self.calculate_attribution(df_combined)
                results = self.aggregate_results(df_attribution)
            
            # 将微观归因结果转为列表，供前端表格展示
            trades_list = df_attribution.to_dict(orient='records')
            # 处理 Timestamp 对象为字符串
            for t in trades_list:
                if isinstance(t.get('timestamp'), (pd.Timestamp, datetime)):
                    t['timestamp'] = t['timestamp'].isoformat()
            
            results['signal_level_details'] = trades_list
            results['trades'] = trades_list # Alias for frontend compatibility
            
            # Ensure all types are standard Python types for JSON serialization
            return self._to_python_types(results)
        
        except Exception as e:
            logger.error(f"Attribution calculation failed for strategy={strategy_id}: {e}", exc_info=True)
            res = empty_result.copy()
            res["error"] = f"Attribution calculation failed: {str(e)}"
            return res

    async def get_attribution_comparison(
        self,
        strategy_id: str,
        base_mode: str = "backtest",
        compare_mode: str = "historical_replay",
        session_id: Optional[str] = None,
        symbol: Optional[str] = None,
        days: int = 7,
    ) -> Dict[str, Any]:
        """
        获取两个模式（backtest vs historical_replay/paper）的归因数据对比。
        
        Args:
            strategy_id: 策略ID
            base_mode: 基准模式 (backtest)
            compare_mode: 比较模式 (historical_replay 或 paper)
            session_id: 回放session ID（仅compare_mode为historical_replay时需要）
            symbol: 交易对
            days: 时间范围（天）
        
        Returns:
            两个模式的归因数据对比，包含每个维度的差异分析
        """
        # 获取 compare_mode 的归因分析
        compare_attribution = await self.get_strategy_attribution(
            strategy_id=strategy_id,
            symbol=symbol,
            days=days,
            base_mode="backtest",
            compare_mode=compare_mode,
            replay_session_id=session_id,
        )
        
        # 如果有错误，返回错误信息
        if "error" in compare_attribution:
            return {
                "error": compare_attribution.get("error"),
                "base_mode": base_mode,
                "compare_mode": compare_mode,
                "comparison": None,
            }
        
        # 提取全局归因数据
        global_agg = compare_attribution.get("global_agg", compare_attribution.get("global", {}))
        
        # 构建对比结果
        comparison_metrics = [
            {
                "metric": "delta_price",
                "label": "价格差异",
                "value": global_agg.get("delta_price", 0),
                "interpretation": self._interpret_delta(global_agg.get("delta_price", 0), "price"),
            },
            {
                "metric": "delta_fill",
                "label": "成交率差异",
                "value": global_agg.get("delta_fill", 0),
                "interpretation": self._interpret_delta(global_agg.get("delta_fill", 0), "fill"),
            },
            {
                "metric": "delta_fees",
                "label": "手续费差异",
                "value": global_agg.get("delta_fees", 0),
                "interpretation": self._interpret_delta(global_agg.get("delta_fees", 0), "fees"),
            },
            {
                "metric": "delta_total",
                "label": "总差异",
                "value": global_agg.get("delta_total", 0),
                "interpretation": self._interpret_delta(global_agg.get("delta_total", 0), "total"),
            },
            {
                "metric": "total_slippage_impact",
                "label": "滑点影响总计",
                "value": global_agg.get("total_slippage_impact", 0),
                "interpretation": self._interpret_slippage(global_agg.get("total_slippage_impact", 0)),
            },
            {
                "metric": "total_latency_impact",
                "label": "延迟影响总计",
                "value": global_agg.get("total_latency_impact", 0),
                "interpretation": self._interpret_latency(global_agg.get("total_latency_impact", 0)),
            },
            {
                "metric": "avg_execution_quality",
                "label": "平均执行质量",
                "value": global_agg.get("avg_execution_quality"),
                "interpretation": self._interpret_execution_quality(global_agg.get("avg_execution_quality")),
            },
            {
                "metric": "avg_timing_diff",
                "label": "平均执行延迟(秒)",
                "value": global_agg.get("avg_timing_diff"),
                "interpretation": self._interpret_timing(global_agg.get("avg_timing_diff")),
            },
        ]
        
        return {
            "strategy_id": strategy_id,
            "base_mode": base_mode,
            "compare_mode": compare_mode,
            "session_id": session_id,
            "symbol": symbol,
            "bt_total_pnl": global_agg.get("bt_total_pnl", 0),
            "compare_total_pnl": global_agg.get("sim_total_pnl", 0),
            "comparison_metrics": comparison_metrics,
            "daily_breakdown": compare_attribution.get("daily", []),
            "symbol_breakdown": compare_attribution.get("symbol", []),
            "trade_count": len(compare_attribution.get("trades", [])),
        }
    
    def _interpret_delta(self, value: float, delta_type: str) -> str:
        """解释差异值的含义"""
        if value is None:
            return "数据不可用"
        if abs(value) < 0.01:
            return "基本一致"
        if delta_type == "total":
            return "实盘优于回测" if value > 0 else "实盘劣于回测"
        if delta_type == "fees":
            return "实盘手续费更低" if value > 0 else "实盘手续费更高"
        return "实盘表现更好" if value > 0 else "实盘表现较差"
    
    def _interpret_slippage(self, value: float) -> str:
        """解释滑点影响"""
        if value is None:
            return "数据不可用"
        if abs(value) < 1:
            return "滑点影响可忽略"
        if value > 0:
            return f"不利滑点，损失约 ${abs(value):.2f}"
        return f"有利滑点，节省约 ${abs(value):.2f}"
    
    def _interpret_latency(self, value: float) -> str:
        """解释延迟影响"""
        if value is None:
            return "数据不可用"
        if abs(value) < 1:
            return "延迟影响可忽略"
        return f"延迟导致潜在损失约 ${abs(value):.2f}"
    
    def _interpret_execution_quality(self, value: Optional[float]) -> str:
        """解释执行质量评分"""
        if value is None:
            return "数据不可用"
        if value >= 90:
            return "优秀"
        if value >= 70:
            return "良好"
        if value >= 50:
            return "一般"
        return "较差，建议优化执行策略"
    
    def _interpret_timing(self, value: Optional[float]) -> str:
        """解释执行延迟"""
        if value is None:
            return "数据不可用"
        if value < 1:
            return "延迟极低"
        if value < 5:
            return "延迟正常"
        if value < 30:
            return "延迟偏高"
        return "延迟过高，需要优化"

# Singleton instance
attribution_service = AttributionService()
