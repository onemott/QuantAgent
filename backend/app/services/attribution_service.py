import logging
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from sqlalchemy import select, func
from app.services.database import get_db
from app.models.db_models import PaperTrade, BacktestResult

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
        核心归因计算函数
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
        
        # 3.6 总差异校验
        df['delta_total'] = df['delta_price'] + df['delta_fill'] + df['delta_timing'] + df['delta_fees']
        
        return df

    def aggregate_results(self, df_attribution: pd.DataFrame) -> Dict[str, Any]:
        """
        结果聚合函数：按日、按品种、全局
        """
        if df_attribution.empty:
            return {
                "daily": [],
                "symbol": [],
                "global": {}
            }
            
        # 确保 timestamp 为 datetime 类型
        df_attribution['timestamp'] = pd.to_datetime(df_attribution['timestamp'])
        df_attribution['date'] = df_attribution['timestamp'].dt.date
        
        diff_cols = ['delta_price', 'delta_fill', 'delta_timing', 'delta_fees', 'delta_total']
        
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
                "delta_price": 0, "delta_fill": 0, "delta_timing": 0, "delta_fees": 0, "delta_total": 0
            },
            "signal_level_details": []
        }

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
                res = empty_result.copy()
                res["error"] = "No backtest result found for alignment"
                return res
                
            # 解析成交数据为 DataFrame
            sim_exec_data = []
            for t in sim_trades:
                sim_exec_data.append({
                    'signal_id': t.client_order_id or f"SIM_{t.id}",
                    'symbol': t.symbol,
                    'side': t.side,
                    'exec_qty': float(t.quantity),
                    'exec_price': float(t.price),
                    'fee': float(t.fee),
                    'exec_ts': t.created_at
                })
            df_sim_exec = pd.DataFrame(sim_exec_data)
            
            # 从 BacktestResult 解析 bt_exec
            bt_trades = bt_result.trades_summary
            if not bt_trades:
                res = empty_result.copy()
                res["error"] = "Backtest result has no trades"
                return res

            bt_exec_data = []
            signal_data = []
            
            for i, bt_t in enumerate(bt_trades):
                # 生成对齐键
                sig_id = f"SIG_{bt_t['entry_time']}_{bt_t.get('symbol', symbol)}"
                
                # 回测成交数据
                bt_exec_data.append({
                    'signal_id': sig_id,
                    'symbol': bt_t.get('symbol', symbol),
                    'exec_qty': float(bt_t['quantity']),
                    'exec_price': float(bt_t['entry_price']),
                    'fee': float(bt_t.get('fee', 0.0)),
                    'exec_ts': pd.to_datetime(bt_t['entry_time'])
                })
                
                # 信号表数据 (QAD 核心表)
                signal_data.append({
                    'signal_id': sig_id,
                    'timestamp': pd.to_datetime(bt_t['entry_time']),
                    'symbol': bt_t.get('symbol', symbol),
                    'direction': 1, # 假设是买入，实际需根据 backtest 逻辑对齐
                    'target_qty': float(bt_t['quantity']),
                    'trigger_price': float(bt_t['entry_price'])
                })
            
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

# Singleton instance
attribution_service = AttributionService()
