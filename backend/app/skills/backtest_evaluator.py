"""
回测评估Skill
评估策略在历史数据上的表现
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

from app.skills.core.base import BaseSkill
from app.skills.core.models import SkillDefinition, SkillType


logger = logging.getLogger(__name__)


class BacktestEvaluatorSkill(BaseSkill):
    """
    回测评估Skill
    
    功能：
    1. 执行策略回测
    2. 计算性能指标
    3. 风险评估
    4. 生成详细报告
    
    输入：策略配置、历史数据
    输出：回测结果、性能指标、风险评估
    """

    RISK_FREE_RATE = 0.03
    SECONDS_PER_YEAR = 365.2425 * 24 * 60 * 60
    MIN_OBSERVATIONS_FOR_RISK_METRICS = 2
    INTERVAL_SECONDS = {
        "1m": 60,
        "3m": 180,
        "5m": 300,
        "15m": 900,
        "30m": 1800,
        "1h": 3600,
        "2h": 7200,
        "4h": 14400,
        "6h": 21600,
        "8h": 28800,
        "12h": 43200,
        "1d": 86400,
        "3d": 259200,
        "1w": 604800,
    }
    
    def __init__(self, skill_definition: SkillDefinition):
        super().__init__(skill_definition)
        self.required_dependencies = ["pandas", "numpy"]
        
        # 性能指标权重配置
        self.metric_weights = {
            "sharpe_ratio": 0.25,
            "max_drawdown": 0.20,
            "total_return": 0.15,
            "win_rate": 0.15,
            "profit_factor": 0.10,
            "calmar_ratio": 0.10,
            "sortino_ratio": 0.05
        }
        
        # 风险评估阈值
        self.risk_thresholds = {
            "max_drawdown_severe": -0.40,   # 严重回撤
            "max_drawdown_high": -0.25,     # 高回撤
            "max_drawdown_medium": -0.15,   # 中等回撤
            "sharpe_low": 0.5,              # 低夏普比率
            "sharpe_good": 1.0,             # 良好夏普比率
            "sharpe_excellent": 2.0,        # 优秀夏普比率
            "win_rate_low": 0.4,            # 低胜率
            "win_rate_good": 0.5,           # 良好胜率
            "profit_factor_low": 1.0,       # 低盈利因子
            "profit_factor_good": 1.5,      # 良好盈利因子
        }
    
    async def execute(self, inputs: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        执行回测评估
        
        输入格式：
        {
            "strategies": [
                {
                    "strategy_id": "strategy_001",
                    "name": "趋势跟踪策略",
                    "type": "trend_following",
                    "parameters": {
                        "ma_fast_period": 5,
                        "ma_slow_period": 20,
                        "entry_threshold": 0.02,
                        "exit_threshold": 0.01
                    }
                },
                ...
            ],
            "market_data": {
                "symbol": "BTCUSDT",
                "interval": "1d",
                "ohlcv": [...],  # OHLCV数据
                "indicators": {...}  # 技术指标（可选）
            },
            "backtest_config": {
                "initial_capital": 10000,
                "commission_rate": 0.001,  # 手续费率
                "slippage": 0.001,         # 滑点
                "position_size": 0.1,      # 仓位大小
                "test_periods": [          # 测试周期
                    {"start": "2024-01-01", "end": "2024-06-30"},
                    {"start": "2024-07-01", "end": "2024-12-31"}
                ]
            },
            "evaluation_config": {
                "include_metrics": ["sharpe", "max_drawdown", "total_return"],
                "risk_assessment": true,
                "comparative_analysis": true,
                "generate_report": true
            }
        }
        
        输出格式：
        {
            "evaluation_results": [
                {
                    "strategy_id": "strategy_001",
                    "strategy_name": "趋势跟踪策略",
                    "backtest_performance": {
                        "total_return": 0.25,
                        "annual_return": 0.50,
                        "sharpe_ratio": 1.35,
                        "sortino_ratio": 1.85,
                        "calmar_ratio": 1.20,
                        "max_drawdown": -0.18,
                        "max_drawdown_duration": 45,
                        "win_rate": 0.52,
                        "profit_factor": 1.48,
                        "total_trades": 120,
                        "winning_trades": 62,
                        "losing_trades": 58,
                        "avg_win": 0.032,
                        "avg_loss": -0.025,
                        "largest_win": 0.085,
                        "largest_loss": -0.062
                    },
                    "risk_assessment": {
                        "risk_level": "medium",  # low, medium, high
                        "risk_score": 0.65,
                        "risk_factors": [
                            {"factor": "回撤控制", "score": 0.7, "assessment": "良好"},
                            {"factor": "稳定性", "score": 0.6, "assessment": "中等"},
                            {"factor": "夏普比率", "score": 0.8, "assessment": "优秀"}
                        ],
                        "warnings": [
                            "最大回撤接近阈值",
                            "胜率偏低"
                        ],
                        "recommendations": [
                            "建议增加止损策略",
                            "考虑降低仓位以控制风险"
                        ]
                    },
                    "period_analysis": {
                        "overall": {...},
                        "period_1": {...},
                        "period_2": {...}
                    },
                    "ranking": {
                        "overall_rank": 2,
                        "total_strategies": 10,
                        "performance_rank": 2,
                        "risk_rank": 3,
                        "composite_score": 0.72
                    }
                },
                ...
            ],
            "comparative_analysis": {
                "best_strategy": "strategy_002",
                "worst_strategy": "strategy_005",
                "strategy_comparison": [...],
                "metric_summary": {
                    "avg_sharpe": 1.15,
                    "avg_drawdown": -0.22,
                    "best_sharpe": 1.85,
                    "best_drawdown": -0.12
                }
            },
            "evaluation_summary": {
                "total_strategies_evaluated": 10,
                "successful_evaluations": 9,
                "failed_evaluations": 1,
                "total_execution_time": 12.5,
                "avg_execution_time_per_strategy": 1.25,
                "overall_assessment": "良好"
            }
        }
        """
        start_time = time.time()
        
        try:
            # 1. 解析输入
            strategies = inputs.get("strategies", [])
            market_data = inputs.get("market_data", {})
            backtest_config = inputs.get("backtest_config", {})
            evaluation_config = inputs.get("evaluation_config", {})
            
            if not strategies:
                return {
                    "error": "没有提供策略配置",
                    "evaluation_results": [],
                    "evaluation_summary": {
                        "total_strategies_evaluated": 0,
                        "successful_evaluations": 0,
                        "failed_evaluations": 0,
                        "total_execution_time": 0,
                        "overall_assessment": "无数据"
                    }
                }
            
            # 2. 准备历史数据
            prepared_data = await self._prepare_market_data(market_data)
            
            # 3. 执行策略回测
            evaluation_results = []
            successful_count = 0
            failed_count = 0
            
            for strategy_config in strategies:
                try:
                    result = await self._evaluate_single_strategy(
                        strategy_config,
                        prepared_data,
                        backtest_config,
                        evaluation_config
                    )
                    evaluation_results.append(result)
                    successful_count += 1
                    
                except Exception as e:
                    print(f"⚠️ 策略评估失败 {strategy_config.get('strategy_id', 'unknown')}: {e}")
                    failed_count += 1
                    
                    # 创建失败结果
                    failed_result = {
                        "strategy_id": strategy_config.get("strategy_id", "unknown"),
                        "strategy_name": strategy_config.get("name", "未知策略"),
                        "backtest_performance": {},
                        "risk_assessment": {
                            "risk_level": "unknown",
                            "risk_score": 0,
                            "error": str(e)
                        },
                        "ranking": {
                            "overall_rank": 0,
                            "total_strategies": len(strategies),
                            "composite_score": 0
                        }
                    }
                    evaluation_results.append(failed_result)
            
            # 4. 执行比较分析
            comparative_analysis = {}
            if evaluation_config.get("comparative_analysis", True) and evaluation_results:
                comparative_analysis = await self._perform_comparative_analysis(evaluation_results)
            
            # 5. 计算总体评估
            end_time = time.time()
            total_execution_time = end_time - start_time
            
            evaluation_summary = {
                "total_strategies_evaluated": len(strategies),
                "successful_evaluations": successful_count,
                "failed_evaluations": failed_count,
                "total_execution_time": round(total_execution_time, 3),
                "avg_execution_time_per_strategy": (
                    round(total_execution_time / len(strategies), 3) 
                    if strategies else 0
                ),
                "overall_assessment": self._get_overall_assessment(evaluation_results)
            }
            
            # 6. 构建输出
            result = {
                "evaluation_results": evaluation_results,
                "evaluation_summary": evaluation_summary
            }
            
            if comparative_analysis:
                result["comparative_analysis"] = comparative_analysis
            
            # 添加执行上下文
            if context:
                result["_context"] = {
                    "execution_id": context.get("execution_id"),
                    "skill_version": self.skill_definition.version,
                    "timestamp": datetime.utcnow().isoformat(),
                    "market_data_summary": {
                        "symbol": market_data.get("symbol"),
                        "interval": market_data.get("interval"),
                        "data_points": len(market_data.get("ohlcv", [])),
                        "period": self._get_data_period(market_data)
                    }
                }
            
            return result
            
        except Exception as e:
            raise RuntimeError(f"回测评估失败: {str(e)}")
    
    async def _prepare_market_data(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """准备市场数据"""
        prepared = {
            "symbol": market_data.get("symbol", "UNKNOWN"),
            "interval": market_data.get("interval", "1d"),
            "ohlcv_df": None,
            "indicators": market_data.get("indicators", {}),
            "data_quality": "unknown"
        }
        
        # 转换OHLCV数据为DataFrame
        ohlcv = market_data.get("ohlcv", [])
        if ohlcv and len(ohlcv) > 0:
            try:
                # 假设ohlcv是字典列表
                df = pd.DataFrame(ohlcv)
                
                # 确保必要的列存在
                required_cols = ["timestamp", "open", "high", "low", "close", "volume"]
                available_cols = [col for col in required_cols if col in df.columns]
                
                if len(available_cols) >= 4:  # 至少需要OHLC
                    prepared["ohlcv_df"] = df
                    
                    # 评估数据质量
                    prepared["data_quality"] = self._assess_data_quality(df)
                    
                    # 添加基本计算列
                    if "close" in df.columns:
                        df["returns"] = df["close"].pct_change()
                        df["log_returns"] = np.log(df["close"] / df["close"].shift(1))
                
            except Exception as e:
                print(f"⚠️ 数据准备失败: {e}")
        
        return prepared
    
    def _assess_data_quality(self, df: pd.DataFrame) -> str:
        """评估数据质量"""
        if df.empty:
            return "empty"
        
        # 检查缺失值
        missing_ratio = df.isnull().sum().sum() / (df.shape[0] * df.shape[1])
        
        # 检查异常值（基于价格变动）
        if "close" in df.columns:
            returns = df["close"].pct_change().dropna()
            outlier_threshold = returns.abs().quantile(0.99)
            outlier_count = (returns.abs() > outlier_threshold).sum()
            outlier_ratio = outlier_count / len(returns)
        else:
            outlier_ratio = 0
        
        # 评估质量
        if missing_ratio > 0.1 or outlier_ratio > 0.05:
            return "poor"
        elif missing_ratio > 0.05 or outlier_ratio > 0.02:
            return "fair"
        else:
            return "good"
    
    def _get_data_period(self, market_data: Dict[str, Any]) -> str:
        """获取数据周期信息"""
        ohlcv = market_data.get("ohlcv", [])
        if not ohlcv:
            return "unknown"
        
        try:
            # 假设ohlcv有timestamp字段
            timestamps = [item.get("timestamp") for item in ohlcv if item.get("timestamp")]
            if timestamps:
                # 转换为datetime并计算范围
                from datetime import datetime as dt
                
                # 尝试解析时间戳
                parsed_times = []
                for ts in timestamps:
                    try:
                        if isinstance(ts, (int, float)):
                            # Unix时间戳
                            parsed_times.append(dt.fromtimestamp(ts))
                        elif isinstance(ts, str):
                            # 字符串时间戳
                            for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"]:
                                try:
                                    parsed_times.append(dt.strptime(ts, fmt))
                                    break
                                except ValueError:
                                    continue
                    except:
                        pass
                
                if parsed_times:
                    start_date = min(parsed_times).strftime("%Y-%m-%d")
                    end_date = max(parsed_times).strftime("%Y-%m-%d")
                    days = (max(parsed_times) - min(parsed_times)).days
                    
                    return f"{start_date} 至 {end_date} ({days}天)"
        
        except Exception as e:
            print(f"⚠️ 获取数据周期失败: {e}")
        
        return f"{len(ohlcv)} 个数据点"
    
    async def _evaluate_single_strategy(
        self,
        strategy_config: Dict[str, Any],
        market_data: Dict[str, Any],
        backtest_config: Dict[str, Any],
        evaluation_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """评估单个策略"""
        strategy_id = strategy_config.get("strategy_id", "unknown")
        strategy_type = strategy_config.get("type", "unknown")
        
        print(f"🔍 评估策略: {strategy_id} ({strategy_type})")
        
        # 1. 运行回测（简化版）
        backtest_result = await self._run_simplified_backtest(
            strategy_config, 
            market_data, 
            backtest_config
        )
        
        # 2. 计算性能指标
        performance_metrics = self._calculate_performance_metrics(backtest_result)
        
        # 3. 风险评估
        risk_assessment = self._assess_risk(performance_metrics, strategy_config)
        
        # 4. 计算综合评分
        composite_score = self._calculate_composite_score(performance_metrics)
        
        # 5. 构建结果
        result = {
            "strategy_id": strategy_id,
            "strategy_name": strategy_config.get("name", "未知策略"),
            "strategy_type": strategy_type,
            "backtest_performance": performance_metrics,
            "risk_assessment": risk_assessment,
            "ranking": {
                "composite_score": composite_score,
                "performance_score": self._calculate_performance_score(performance_metrics),
                "risk_score": risk_assessment.get("risk_score", 0.5)
            },
            "backtest_details": {
                "trades_executed": backtest_result.get("total_trades", 0),
                "initial_capital": backtest_config.get("initial_capital", 10000),
                "final_capital": backtest_result.get("final_capital", 0),
                "commission_paid": backtest_result.get("total_commission", 0)
            }
        }
        
        # 6. 添加周期分析（如果配置了多个测试周期）
        if evaluation_config.get("period_analysis", False):
            result["period_analysis"] = await self._analyze_by_period(
                strategy_config, market_data, backtest_config
            )
        
        return result
    
    async def _run_simplified_backtest(
        self,
        strategy_config: Dict[str, Any],
        market_data: Dict[str, Any],
        backtest_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """运行简化版回测，生成可验证的权益曲线与交易统计。"""
        strategy_type = strategy_config.get("type", "unknown")
        parameters = strategy_config.get("parameters", {})
        initial_capital = float(backtest_config.get("initial_capital", 10000))
        commission_rate = float(backtest_config.get("commission_rate", 0.001))
        slippage = float(backtest_config.get("slippage", 0.0))
        warnings: List[str] = []

        ohlcv_df = market_data.get("ohlcv_df")
        if not isinstance(ohlcv_df, pd.DataFrame) or ohlcv_df.empty or "close" not in ohlcv_df.columns:
            warning = "缺少有效的 OHLCV 收盘价数据，无法执行回测。"
            logger.warning(warning)
            return self._build_empty_backtest_result(
                initial_capital=initial_capital,
                annualization_factor=1,
                data_period_years=0.0,
                data_period_days=0.0,
                warnings=[warning],
            )

        price_frame = ohlcv_df.copy()
        price_frame["close"] = pd.to_numeric(price_frame["close"], errors="coerce")
        price_frame = price_frame.dropna(subset=["close"]).reset_index(drop=True)
        if len(price_frame) < 2:
            warning = "有效价格数据不足 2 条，无法计算收益率序列。"
            logger.warning(warning)
            return self._build_empty_backtest_result(
                initial_capital=initial_capital,
                annualization_factor=1,
                data_period_years=0.0,
                data_period_days=0.0,
                warnings=[warning],
            )

        period_context = self._resolve_period_context(
            market_data=market_data,
            backtest_config=backtest_config,
            observation_count=len(price_frame),
        )
        param_adjustments = self._adjust_results_by_parameters(parameters, strategy_type)
        base_position_size = float(backtest_config.get("position_size", 0.1))
        adjusted_position_size = min(
            max(base_position_size * float(param_adjustments.get("total_return", 1.0)), 0.0),
            1.0,
        )

        close_prices = pd.Series(price_frame["close"], dtype=float)
        asset_returns = close_prices.pct_change().fillna(0.0)
        raw_positions = self._generate_strategy_positions(close_prices, strategy_type, parameters)
        positions = (raw_positions * adjusted_position_size).clip(lower=0.0, upper=1.0)
        executed_positions = positions.shift(1).fillna(0.0)
        turnover = executed_positions.diff().abs().fillna(executed_positions.abs())

        total_cost_rate = commission_rate + slippage
        strategy_returns = (executed_positions * asset_returns) - (turnover * total_cost_rate)
        equity_curve = initial_capital * (1 + strategy_returns).cumprod()
        final_capital = float(equity_curve.iloc[-1])
        total_return = (final_capital / initial_capital - 1) if initial_capital > 0 else 0.0

        commission_cash = (
            turnover * commission_rate * equity_curve.shift(1).fillna(initial_capital)
        ).sum()
        trade_stats = self._extract_trade_statistics(
            close_prices=close_prices,
            executed_positions=raw_positions.shift(1).fillna(0.0),
            commission_rate=commission_rate,
            slippage=slippage,
        )
        warnings.extend(trade_stats.pop("warnings", []))

        return {
            "initial_capital": initial_capital,
            "final_capital": final_capital,
            "total_return": total_return,
            "total_commission": float(commission_cash),
            "period_returns": strategy_returns.tolist(),
            "equity_curve": equity_curve.tolist(),
            "annualization_factor": period_context["annualization_factor"],
            "data_period_years": period_context["data_period_years"],
            "data_period_days": period_context["data_period_days"],
            "position_size": adjusted_position_size,
            "warnings": warnings,
            **trade_stats,
        }

    def _build_empty_backtest_result(
        self,
        initial_capital: float,
        annualization_factor: int,
        data_period_years: float,
        data_period_days: float,
        warnings: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """构建零交易/无数据场景的统一回测结果。"""
        return {
            "initial_capital": initial_capital,
            "final_capital": initial_capital,
            "total_return": 0.0,
            "total_commission": 0.0,
            "period_returns": [],
            "equity_curve": [initial_capital],
            "trade_returns": [],
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "largest_win": 0.0,
            "largest_loss": 0.0,
            "win_rate": 0.0,
            "annualization_factor": annualization_factor,
            "data_period_years": data_period_years,
            "data_period_days": data_period_days,
            "warnings": warnings or [],
        }

    def _resolve_period_context(
        self,
        market_data: Dict[str, Any],
        backtest_config: Dict[str, Any],
        observation_count: int,
    ) -> Dict[str, Any]:
        """
        基于真实数据跨度推导年化参数。

        优先使用 OHLCV 时间戳，其次回退到 test_periods，再其次用 interval * 数据点数估算。
        """
        timestamps = self._extract_market_timestamps(market_data)
        bar_seconds = self._infer_interval_seconds(market_data.get("interval", "1d"))

        if len(timestamps) >= 2:
            diffs = pd.Series(timestamps).diff().dropna().dt.total_seconds()
            positive_diffs = diffs[diffs > 0]
            if not positive_diffs.empty:
                bar_seconds = float(positive_diffs.median())
            period_seconds = float((timestamps[-1] - timestamps[0]).total_seconds())
        else:
            period_seconds = self._extract_test_period_seconds(backtest_config)
            if period_seconds <= 0:
                period_seconds = float(max(observation_count - 1, 1) * bar_seconds)

        annualization_factor = max(int(round(self.SECONDS_PER_YEAR / max(bar_seconds, 1.0))), 1)
        data_period_years = max(period_seconds / self.SECONDS_PER_YEAR, 1.0 / annualization_factor)
        data_period_days = period_seconds / 86400 if period_seconds > 0 else 0.0

        return {
            "annualization_factor": annualization_factor,
            "data_period_years": float(data_period_years),
            "data_period_days": float(data_period_days),
        }

    def _extract_market_timestamps(self, market_data: Dict[str, Any]) -> List[datetime]:
        """从市场数据中提取并排序时间戳。"""
        ohlcv_df = market_data.get("ohlcv_df")
        raw_timestamps: List[Any] = []

        if isinstance(ohlcv_df, pd.DataFrame) and "timestamp" in ohlcv_df.columns:
            raw_timestamps = ohlcv_df["timestamp"].tolist()
        else:
            ohlcv = market_data.get("ohlcv", [])
            raw_timestamps = [
                item.get("timestamp")
                for item in ohlcv
                if isinstance(item, dict) and item.get("timestamp") is not None
            ]

        if not raw_timestamps:
            return []

        timestamp_series = pd.Series(raw_timestamps)
        if pd.api.types.is_numeric_dtype(timestamp_series):
            median_value = float(timestamp_series.dropna().abs().median()) if not timestamp_series.dropna().empty else 0.0
            unit = "ms" if median_value >= 1e12 else "s"
            parsed = pd.to_datetime(timestamp_series, unit=unit, errors="coerce", utc=True)
        else:
            parsed = pd.to_datetime(timestamp_series, errors="coerce", utc=True)

        parsed_index = pd.DatetimeIndex(parsed.dropna()).sort_values().unique()
        return [ts.to_pydatetime() for ts in parsed_index]

    def _extract_test_period_seconds(self, backtest_config: Dict[str, Any]) -> float:
        """从配置中的测试区间提取总跨度，作为时间戳缺失时的回退方案。"""
        test_periods = backtest_config.get("test_periods", [])
        if not test_periods:
            return 0.0

        parsed_bounds: List[Tuple[datetime, datetime]] = []
        for period in test_periods:
            start = pd.to_datetime(period.get("start"), errors="coerce")
            end = pd.to_datetime(period.get("end"), errors="coerce")
            if pd.isna(start) or pd.isna(end):
                continue
            parsed_bounds.append((start.to_pydatetime(), end.to_pydatetime()))

        if not parsed_bounds:
            return 0.0

        start_dt = min(bound[0] for bound in parsed_bounds)
        end_dt = max(bound[1] for bound in parsed_bounds)
        return float(max((end_dt - start_dt).total_seconds(), 0.0))

    def _infer_interval_seconds(self, interval: str) -> int:
        """将常见 K 线周期解析为秒数。"""
        normalized_interval = str(interval or "1d").strip().lower()
        if normalized_interval in self.INTERVAL_SECONDS:
            return self.INTERVAL_SECONDS[normalized_interval]

        if normalized_interval.endswith("m") and normalized_interval[:-1].isdigit():
            return int(normalized_interval[:-1]) * 60
        if normalized_interval.endswith("h") and normalized_interval[:-1].isdigit():
            return int(normalized_interval[:-1]) * 3600
        if normalized_interval.endswith("d") and normalized_interval[:-1].isdigit():
            return int(normalized_interval[:-1]) * 86400

        return 86400

    def _generate_strategy_positions(
        self,
        close_prices: pd.Series,
        strategy_type: str,
        parameters: Dict[str, Any],
    ) -> pd.Series:
        """根据策略类型生成简化版 long-only 持仓序列。"""
        close_prices = pd.Series(close_prices, dtype=float)

        if strategy_type == "trend_following":
            fast_period = max(int(parameters.get("ma_fast_period", 5)), 1)
            slow_period = max(int(parameters.get("ma_slow_period", 20)), fast_period + 1)
            fast_ma = close_prices.rolling(window=fast_period, min_periods=fast_period).mean()
            slow_ma = close_prices.rolling(window=slow_period, min_periods=slow_period).mean()
            return (fast_ma > slow_ma).astype(float).fillna(0.0)

        if strategy_type == "mean_reversion":
            rsi_period = max(int(parameters.get("rsi_period", 14)), 2)
            oversold = float(parameters.get("oversold_threshold", 30.0))
            exit_rsi = float(parameters.get("exit_rsi", 55.0))
            rsi = self._calculate_rsi(close_prices, rsi_period)
            return self._build_stateful_position(rsi < oversold, rsi > exit_rsi, close_prices.index)

        if strategy_type == "breakout":
            breakout_period = max(int(parameters.get("breakout_period", 20)), 2)
            rolling_high = close_prices.shift(1).rolling(window=breakout_period, min_periods=breakout_period).max()
            rolling_low = close_prices.shift(1).rolling(window=breakout_period, min_periods=breakout_period).min()
            return self._build_stateful_position(close_prices > rolling_high, close_prices < rolling_low, close_prices.index)

        if strategy_type == "momentum":
            lookback_period = max(int(parameters.get("lookback_period", 10)), 1)
            entry_threshold = float(parameters.get("entry_threshold", 0.0))
            momentum = close_prices.pct_change(lookback_period)
            return self._build_stateful_position(momentum > entry_threshold, momentum < 0, close_prices.index)

        fallback_signal = close_prices.pct_change().rolling(window=5, min_periods=5).mean()
        return (fallback_signal > 0).astype(float).fillna(0.0)

    def _build_stateful_position(
        self,
        entry_signal: pd.Series,
        exit_signal: pd.Series,
        index: pd.Index,
    ) -> pd.Series:
        """将离散的入场/出场条件转换为持仓状态。"""
        position_state = pd.Series(0.0, index=index, dtype=float)
        current_position = 0.0

        for idx in index:
            if bool(entry_signal.loc[idx]):
                current_position = 1.0
            elif bool(exit_signal.loc[idx]):
                current_position = 0.0
            position_state.loc[idx] = current_position

        return position_state

    def _calculate_rsi(self, close_prices: pd.Series, period: int) -> pd.Series:
        """计算 RSI，用于均值回归策略的简化信号。"""
        delta = close_prices.diff()
        gains = delta.clip(lower=0.0)
        losses = -delta.clip(upper=0.0)

        avg_gain = gains.rolling(window=period, min_periods=period).mean()
        avg_loss = losses.rolling(window=period, min_periods=period).mean()
        relative_strength = avg_gain / avg_loss.replace(0.0, np.nan)
        rsi = 100 - (100 / (1 + relative_strength))
        return rsi.fillna(50.0)

    def _extract_trade_statistics(
        self,
        close_prices: pd.Series,
        executed_positions: pd.Series,
        commission_rate: float,
        slippage: float,
    ) -> Dict[str, Any]:
        """基于真实进出场序列统计交易结果，不再伪造平均盈亏。"""
        position_state = pd.Series(executed_positions, dtype=float).fillna(0.0).clip(lower=0.0, upper=1.0)
        trade_returns: List[float] = []
        in_position = False
        entry_price = 0.0

        for i, current_price in enumerate(close_prices):
            current_signal = float(position_state.iloc[i])
            previous_signal = float(position_state.iloc[i - 1]) if i > 0 else 0.0

            if not in_position and previous_signal <= 0.0 and current_signal > 0.0:
                entry_price = float(current_price)
                in_position = True
                continue

            if in_position and previous_signal > 0.0 and current_signal <= 0.0:
                exit_price = float(current_price)
                gross_return = (exit_price / entry_price - 1) if entry_price > 0 else 0.0
                net_return = gross_return - (2 * commission_rate) - slippage
                trade_returns.append(float(net_return))
                in_position = False

        if in_position and entry_price > 0:
            final_price = float(close_prices.iloc[-1])
            gross_return = final_price / entry_price - 1
            net_return = gross_return - commission_rate - slippage
            trade_returns.append(float(net_return))

        trade_returns_series = pd.Series(trade_returns, dtype=float)
        winning_trades = trade_returns_series[trade_returns_series > 0]
        losing_trades = trade_returns_series[trade_returns_series < 0]
        total_trades = int(len(trade_returns_series))
        warnings: List[str] = []

        if total_trades == 0:
            warnings.append("策略在测试区间内未产生任何交易。")
            logger.warning("Backtest evaluator produced zero trades for the current strategy window.")

        return {
            "trade_returns": trade_returns_series.tolist(),
            "total_trades": total_trades,
            "winning_trades": int(len(winning_trades)),
            "losing_trades": int(len(losing_trades)),
            "win_rate": float(len(winning_trades) / total_trades) if total_trades > 0 else 0.0,
            "avg_win": float(winning_trades.mean()) if not winning_trades.empty else 0.0,
            "avg_loss": float(losing_trades.mean()) if not losing_trades.empty else 0.0,
            "largest_win": float(winning_trades.max()) if not winning_trades.empty else 0.0,
            "largest_loss": float(losing_trades.min()) if not losing_trades.empty else 0.0,
            "warnings": warnings,
        }
    
    def _adjust_results_by_parameters(self, parameters: Dict[str, Any], strategy_type: str) -> Dict[str, float]:
        """根据策略参数调整结果"""
        adjustments = {}
        
        if strategy_type == "trend_following":
            fast_period = parameters.get("ma_fast_period", 5)
            slow_period = parameters.get("ma_slow_period", 20)
            
            # 参数差异越大，趋势跟踪效果越好
            period_ratio = slow_period / max(fast_period, 1)
            
            if period_ratio > 4:
                adjustments["total_return"] = 1.2
                adjustments["sharpe_ratio"] = 1.1
                adjustments["win_rate"] = 0.9
            elif period_ratio > 2:
                adjustments["total_return"] = 1.1
                adjustments["sharpe_ratio"] = 1.05
                adjustments["win_rate"] = 1.0
            else:
                adjustments["total_return"] = 0.8
                adjustments["sharpe_ratio"] = 0.9
                adjustments["win_rate"] = 0.9
        
        elif strategy_type == "mean_reversion":
            rsi_period = parameters.get("rsi_period", 14)
            
            # RSI周期适中效果最好
            if 10 <= rsi_period <= 20:
                adjustments["total_return"] = 1.1
                adjustments["sharpe_ratio"] = 1.05
            elif rsi_period < 5 or rsi_period > 30:
                adjustments["total_return"] = 0.7
                adjustments["sharpe_ratio"] = 0.8
        
        return adjustments
    
    def _calculate_performance_metrics(self, backtest_result: Dict[str, Any]) -> Dict[str, Any]:
        """基于收益率序列、权益曲线和真实交易统计重新计算性能指标。"""
        warnings = list(backtest_result.get("warnings", []))
        initial_capital = float(backtest_result.get("initial_capital", 0) or 0.0)
        final_capital = float(backtest_result.get("final_capital", initial_capital) or initial_capital)
        total_return = (
            (final_capital / initial_capital - 1)
            if initial_capital > 0
            else float(backtest_result.get("total_return", 0.0) or 0.0)
        )
        annualization_factor = int(backtest_result.get("annualization_factor", 1) or 1)
        data_period_years = float(backtest_result.get("data_period_years", 0.0) or 0.0)

        period_returns = pd.Series(backtest_result.get("period_returns", []), dtype=float).replace([np.inf, -np.inf], np.nan).dropna()
        equity_curve = [float(v) for v in backtest_result.get("equity_curve", []) if v is not None]
        trade_returns = pd.Series(backtest_result.get("trade_returns", []), dtype=float).replace([np.inf, -np.inf], np.nan).dropna()

        max_drawdown, max_drawdown_duration = self._calculate_max_drawdown(equity_curve)
        annual_return = self._annualize_total_return(total_return, data_period_years)
        volatility = self._calculate_annualized_volatility(period_returns, annualization_factor)
        sharpe_ratio = self._calculate_sharpe_ratio(period_returns, annualization_factor, self.RISK_FREE_RATE)
        downside_deviation = self._calculate_downside_deviation(period_returns, annualization_factor, self.RISK_FREE_RATE)

        if volatility <= 0:
            warnings.append("波动率为 0 或数据不足，夏普比率按 0 处理。")
            logger.warning("Backtest evaluator volatility is zero or undefined; Sharpe ratio set to 0.")
            volatility = 0.0
            sharpe_ratio = 0.0

        if downside_deviation <= 0:
            warnings.append("下行波动率为 0 或数据不足，Sortino 比率按 0 处理。")
            logger.warning("Backtest evaluator downside deviation is zero or undefined; Sortino ratio set to 0.")
            sortino_ratio = 0.0
        else:
            sortino_ratio = (annual_return - self.RISK_FREE_RATE) / downside_deviation

        if max_drawdown < 0:
            calmar_ratio = annual_return / abs(max_drawdown)
        else:
            calmar_ratio = 0.0

        total_trades = int(len(trade_returns))
        winning_trades = int((trade_returns > 0).sum())
        losing_trades = int((trade_returns < 0).sum())
        win_rate = float(winning_trades / total_trades) if total_trades > 0 else 0.0

        if total_trades == 0:
            warnings.append("零交易策略：胜率、盈亏比和期望值均按 0 处理。")
            logger.warning("Backtest evaluator encountered a zero-trade strategy.")

        avg_win = float(trade_returns[trade_returns > 0].mean()) if winning_trades > 0 else 0.0
        avg_loss = float(trade_returns[trade_returns < 0].mean()) if losing_trades > 0 else 0.0
        largest_win = float(trade_returns[trade_returns > 0].max()) if winning_trades > 0 else 0.0
        largest_loss = float(trade_returns[trade_returns < 0].min()) if losing_trades > 0 else 0.0

        gross_profit = float(trade_returns[trade_returns > 0].sum()) if winning_trades > 0 else 0.0
        gross_loss = float(abs(trade_returns[trade_returns < 0].sum())) if losing_trades > 0 else 0.0
        if gross_loss > 0:
            profit_factor = gross_profit / gross_loss
        else:
            profit_factor = 0.0
            if gross_profit > 0:
                warnings.append("不存在亏损交易，盈利因子无法按标准公式定义，已按 0 处理。")

        expectancy = float(trade_returns.mean()) if total_trades > 0 else 0.0

        return {
            "total_return": round(total_return, 4),
            "annual_return": round(annual_return, 4),
            "sharpe_ratio": round(sharpe_ratio, 3),
            "sortino_ratio": round(sortino_ratio, 3),
            "calmar_ratio": round(calmar_ratio, 3),
            "max_drawdown": round(max_drawdown, 4),
            "max_drawdown_duration": max_drawdown_duration,
            "win_rate": round(win_rate, 3),
            "profit_factor": round(profit_factor, 3),
            "volatility": round(volatility, 4),
            "downside_deviation": round(downside_deviation, 4),
            "risk_free_rate": self.RISK_FREE_RATE,
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "avg_win": round(avg_win, 4),
            "avg_loss": round(avg_loss, 4),
            "largest_win": round(largest_win, 4),
            "largest_loss": round(largest_loss, 4),
            "expectancy": round(expectancy, 4),
            "warnings": warnings,
        }

    def _calculate_max_drawdown(self, equity_curve: List[float]) -> Tuple[float, int]:
        """基于权益曲线独立计算最大回撤与最长回撤持续期。"""
        if len(equity_curve) < 2:
            return 0.0, 0

        equity_series = pd.Series(equity_curve, dtype=float).replace([np.inf, -np.inf], np.nan).dropna()
        if len(equity_series) < 2:
            return 0.0, 0

        rolling_peak = equity_series.cummax()
        drawdown = (equity_series - rolling_peak) / rolling_peak.replace(0.0, np.nan)
        drawdown = drawdown.fillna(0.0)

        current_duration = 0
        max_duration = 0
        for value in drawdown:
            if value < 0:
                current_duration += 1
                max_duration = max(max_duration, current_duration)
            else:
                current_duration = 0

        return float(drawdown.min()), int(max_duration)

    def _annualize_total_return(self, total_return: float, data_period_years: float) -> float:
        """按真实数据跨度计算年化收益率。"""
        if data_period_years <= 0:
            return 0.0
        if total_return <= -1.0:
            return -1.0
        return float((1 + total_return) ** (1 / data_period_years) - 1)

    def _calculate_annualized_volatility(self, period_returns: pd.Series, annualization_factor: int) -> float:
        """计算年化波动率；数据不足或标准差为 0 时返回 0。"""
        if len(period_returns) < self.MIN_OBSERVATIONS_FOR_RISK_METRICS or annualization_factor <= 0:
            return 0.0

        volatility = float(period_returns.std(ddof=1) * np.sqrt(annualization_factor))
        return volatility if np.isfinite(volatility) and volatility > 0 else 0.0

    def _calculate_sharpe_ratio(
        self,
        period_returns: pd.Series,
        annualization_factor: int,
        risk_free_rate: float,
    ) -> float:
        """按标准公式计算夏普比率。"""
        if len(period_returns) < self.MIN_OBSERVATIONS_FOR_RISK_METRICS or annualization_factor <= 0:
            return 0.0

        risk_free_per_period = risk_free_rate / annualization_factor
        excess_returns = period_returns - risk_free_per_period
        excess_std = float(excess_returns.std(ddof=1))
        if not np.isfinite(excess_std) or excess_std <= 0:
            return 0.0

        return float((excess_returns.mean() / excess_std) * np.sqrt(annualization_factor))

    def _calculate_downside_deviation(
        self,
        period_returns: pd.Series,
        annualization_factor: int,
        risk_free_rate: float,
    ) -> float:
        """计算年化下行波动率，用于 Sortino 比率。"""
        if len(period_returns) < self.MIN_OBSERVATIONS_FOR_RISK_METRICS or annualization_factor <= 0:
            return 0.0

        risk_free_per_period = risk_free_rate / annualization_factor
        downside_excess = np.minimum(period_returns - risk_free_per_period, 0.0)
        downside_variance = float(np.mean(np.square(downside_excess)))
        if not np.isfinite(downside_variance) or downside_variance <= 0:
            return 0.0

        return float(np.sqrt(downside_variance) * np.sqrt(annualization_factor))
    
    def _assess_risk(self, performance_metrics: Dict[str, Any], strategy_config: Dict[str, Any]) -> Dict[str, Any]:
        """风险评估"""
        max_drawdown = performance_metrics.get("max_drawdown", 0)
        sharpe_ratio = performance_metrics.get("sharpe_ratio", 0)
        win_rate = performance_metrics.get("win_rate", 0)
        profit_factor = performance_metrics.get("profit_factor", 0)
        
        # 计算各项风险分数
        drawdown_score = self._calculate_drawdown_score(max_drawdown)
        sharpe_score = self._calculate_sharpe_score(sharpe_ratio)
        consistency_score = self._calculate_consistency_score(win_rate, profit_factor)
        
        # 综合风险分数（加权平均）
        risk_score = (
            drawdown_score["score"] * 0.4 +
            sharpe_score["score"] * 0.3 +
            consistency_score["score"] * 0.3
        )
        
        # 确定风险等级
        if risk_score >= 0.7:
            risk_level = "LOW"
        elif risk_score >= 0.5:
            risk_level = "MEDIUM"
        elif risk_score >= 0.3:
            risk_level = "HIGH"
        else:
            risk_level = "CRITICAL"
        
        # 收集警告
        warnings = []
        if max_drawdown < self.risk_thresholds["max_drawdown_severe"]:
            warnings.append(f"严重回撤: {max_drawdown:.1%}")
        elif max_drawdown < self.risk_thresholds["max_drawdown_high"]:
            warnings.append(f"高回撤: {max_drawdown:.1%}")
        
        if sharpe_ratio < self.risk_thresholds["sharpe_low"]:
            warnings.append(f"夏普比率偏低: {sharpe_ratio:.2f}")
        
        if win_rate < self.risk_thresholds["win_rate_low"]:
            warnings.append(f"胜率偏低: {win_rate:.1%}")
        
        if profit_factor < self.risk_thresholds["profit_factor_low"]:
            warnings.append(f"盈利因子偏低: {profit_factor:.2f}")
        
        # 生成建议
        recommendations = []
        if max_drawdown < -0.2:
            recommendations.append("建议增加止损或降低仓位以控制回撤")
        if win_rate < 0.45:
            recommendations.append("建议优化入场条件以提高胜率")
        if sharpe_ratio < 0.8:
            recommendations.append("建议优化策略参数以提高风险调整后收益")
        
        return {
            "risk_level": risk_level,
            "risk_score": round(risk_score, 3),
            "risk_factors": [
                drawdown_score,
                sharpe_score,
                consistency_score
            ],
            "warnings": warnings,
            "recommendations": recommendations
        }
    
    def _calculate_drawdown_score(self, max_drawdown: float) -> Dict[str, Any]:
        """计算回撤分数"""
        max_drawdown_abs = abs(max_drawdown)
        
        if max_drawdown_abs <= 0.1:
            score = 0.9
            assessment = "优秀"
        elif max_drawdown_abs <= 0.2:
            score = 0.7
            assessment = "良好"
        elif max_drawdown_abs <= 0.3:
            score = 0.5
            assessment = "中等"
        elif max_drawdown_abs <= 0.4:
            score = 0.3
            assessment = "较差"
        else:
            score = 0.1
            assessment = "危险"
        
        return {
            "factor": "回撤控制",
            "score": score,
            "assessment": assessment,
            "value": max_drawdown
        }
    
    def _calculate_sharpe_score(self, sharpe_ratio: float) -> Dict[str, Any]:
        """计算夏普比率分数"""
        if sharpe_ratio >= 2.0:
            score = 1.0
            assessment = "优秀"
        elif sharpe_ratio >= 1.5:
            score = 0.8
            assessment = "很好"
        elif sharpe_ratio >= 1.0:
            score = 0.7
            assessment = "良好"
        elif sharpe_ratio >= 0.5:
            score = 0.5
            assessment = "中等"
        elif sharpe_ratio >= 0:
            score = 0.3
            assessment = "较差"
        else:
            score = 0.1
            assessment = "很差"
        
        return {
            "factor": "夏普比率",
            "score": score,
            "assessment": assessment,
            "value": sharpe_ratio
        }
    
    def _calculate_consistency_score(self, win_rate: float, profit_factor: float) -> Dict[str, Any]:
        """计算一致性分数"""
        # 结合胜率和盈利因子
        win_rate_score = min(win_rate / 0.6, 1.0)  # 60%胜率为满分
        profit_factor_score = min((profit_factor - 1) / 1.5, 1.0)  # 2.5盈利因子为满分
        
        consistency_score = (win_rate_score * 0.6 + profit_factor_score * 0.4)
        
        if consistency_score >= 0.8:
            assessment = "优秀"
        elif consistency_score >= 0.6:
            assessment = "良好"
        elif consistency_score >= 0.4:
            assessment = "中等"
        else:
            assessment = "较差"
        
        return {
            "factor": "策略一致性",
            "score": round(consistency_score, 3),
            "assessment": assessment,
            "win_rate": win_rate,
            "profit_factor": profit_factor
        }
    
    def _calculate_composite_score(self, performance_metrics: Dict[str, Any]) -> float:
        """计算综合评分"""
        score = 0.0
        total_weight = 0.0
        
        for metric_name, weight in self.metric_weights.items():
            metric_value = performance_metrics.get(metric_name)
            if metric_value is not None:
                # 标准化分数
                normalized_score = self._normalize_metric(metric_name, metric_value)
                score += normalized_score * weight
                total_weight += weight
        
        if total_weight > 0:
            final_score = score / total_weight
        else:
            final_score = 0.5
        
        return round(final_score, 3)
    
    def _normalize_metric(self, metric_name: str, metric_value: float) -> float:
        """标准化指标值到0-1范围"""
        if metric_name == "max_drawdown":
            # 回撤越小越好
            return max(0, min(1, 1 + metric_value))  # -0.5 -> 0.5, 0 -> 1
    
        elif metric_name in ["sharpe_ratio", "total_return", "win_rate", "profit_factor", 
                           "calmar_ratio", "sortino_ratio", "volatility"]:
            # 越大越好（对于 volatility，需要在风险评分中反向处理）
            if metric_name == "sharpe_ratio":
                return min(1, max(0, metric_value / 3.0))
            elif metric_name == "total_return":
                return min(1, max(0, metric_value / 1.0))  # 100%回报为满分
            elif metric_name == "win_rate":
                return min(1, max(0, metric_value / 0.8))  # 80%胜率为满分
            elif metric_name == "profit_factor":
                return min(1, max(0, metric_value / 3.0))  # 3.0为满分
            elif metric_name == "calmar_ratio":
                return min(1, max(0, metric_value / 2.0))  # 2.0为满分
            elif metric_name == "sortino_ratio":
                return min(1, max(0, metric_value / 2.5))  # 2.5为满分
            elif metric_name == "volatility":
                # 波动率特殊处理：适中最好（0.15-0.25为理想区间）
                if metric_value < 0.1:
                    return 0.4  # 太低可能意味着机会少
                elif metric_value <= 0.25:
                    return 1.0  # 理想区间
                elif metric_value <= 0.4:
                    return 0.7  # 可接受
                elif metric_value <= 0.6:
                    return 0.5  # 较高
                else:
                    return 0.3  # 过高
    
        return 0.5
    
    def _calculate_performance_score(self, performance_metrics: Dict[str, Any]) -> float:
        """计算纯性能评分（不考虑风险）"""
        performance_metrics_list = ["sharpe_ratio", "total_return", "win_rate", "profit_factor"]
        weights = [0.4, 0.3, 0.2, 0.1]
        
        score = 0.0
        for i, metric_name in enumerate(performance_metrics_list):
            metric_value = performance_metrics.get(metric_name, 0)
            normalized = self._normalize_metric(metric_name, metric_value)
            score += normalized * weights[i]
        
        return round(score, 3)
    
    async def _analyze_by_period(
        self,
        strategy_config: Dict[str, Any],
        market_data: Dict[str, Any],
        backtest_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """按周期分析策略表现"""
        # 简化实现
        return {
            "overall": "完整周期分析",
            "note": "多周期分析功能待实现"
        }
    
    async def _perform_comparative_analysis(self, evaluation_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """执行比较分析"""
        if not evaluation_results:
            return {}
        
        # 过滤掉失败的结果
        valid_results = [r for r in evaluation_results if r.get("backtest_performance")]
        if not valid_results:
            return {}
        
        # 找出最佳和最差策略
        def get_composite_score(result):
            return result.get("ranking", {}).get("composite_score", 0)
        
        valid_results.sort(key=get_composite_score, reverse=True)
        
        best_result = valid_results[0]
        worst_result = valid_results[-1]
        
        # 计算指标摘要
        sharpe_values = [r["backtest_performance"].get("sharpe_ratio", 0) for r in valid_results]
        drawdown_values = [r["backtest_performance"].get("max_drawdown", 0) for r in valid_results]
        return_values = [r["backtest_performance"].get("total_return", 0) for r in valid_results]
        
        # 策略比较表
        strategy_comparison = []
        for i, result in enumerate(valid_results[:10]):  # 只比较前10个
            perf = result["backtest_performance"]
            ranking = result["ranking"]
            
            strategy_comparison.append({
                "rank": i + 1,
                "strategy_id": result["strategy_id"],
                "strategy_name": result["strategy_name"],
                "composite_score": ranking.get("composite_score", 0),
                "sharpe_ratio": perf.get("sharpe_ratio", 0),
                "total_return": perf.get("total_return", 0),
                "max_drawdown": perf.get("max_drawdown", 0),
                "risk_level": result["risk_assessment"].get("risk_level", "unknown")
            })
        
        return {
            "best_strategy": best_result["strategy_id"],
            "worst_strategy": worst_result["strategy_id"],
            "strategy_comparison": strategy_comparison,
            "metric_summary": {
                "avg_sharpe": round(np.mean(sharpe_values), 3),
                "avg_drawdown": round(np.mean(drawdown_values), 4),
                "avg_return": round(np.mean(return_values), 4),
                "best_sharpe": round(max(sharpe_values), 3),
                "best_return": round(max(return_values), 4),
                "best_drawdown": round(max(drawdown_values), 4),  # 注意：回撤是负值，max得到最小的负值
                "sharpe_std": round(np.std(sharpe_values), 3),
                "return_std": round(np.std(return_values), 4)
            }
        }
    
    def _get_overall_assessment(self, evaluation_results: List[Dict[str, Any]]) -> str:
        """获取总体评估"""
        if not evaluation_results:
            return "无数据"
        
        # 计算平均综合评分
        valid_scores = []
        for result in evaluation_results:
            score = result.get("ranking", {}).get("composite_score")
            if score is not None:
                valid_scores.append(score)
        
        if not valid_scores:
            return "评估失败"
        
        avg_score = np.mean(valid_scores)
        
        if avg_score >= 0.7:
            return "优秀"
        elif avg_score >= 0.6:
            return "良好"
        elif avg_score >= 0.5:
            return "中等"
        elif avg_score >= 0.4:
            return "一般"
        else:
            return "较差"
