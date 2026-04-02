"""
回测评估Skill
评估策略在历史数据上的表现
"""

import asyncio
import json
import random
import time
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

from app.skills.core.base import BaseSkill
from app.skills.core.models import SkillDefinition, SkillType


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
        """运行简化版回测（模拟）"""
        
        # 模拟回测结果
        # 在实际项目中，这里应该调用真正的回测引擎
        
        strategy_type = strategy_config.get("type", "unknown")
        parameters = strategy_config.get("parameters", {})
        
        # 基于策略类型生成模拟结果
        base_results = {
            "trend_following": {
                "total_return": 0.15 + (random.random() * 0.3),  # 15-45%
                "sharpe_ratio": 0.8 + (random.random() * 1.2),   # 0.8-2.0
                "max_drawdown": -0.1 - (random.random() * 0.2),  # -10% to -30%
                "win_rate": 0.45 + (random.random() * 0.2),      # 45-65%
                "total_trades": 50 + int(random.random() * 100),  # 50-150 trades
                "volatility": 0.15 + (random.random() * 0.15)   # 15-30%
            },
            "mean_reversion": {
                "total_return": 0.12 + (random.random() * 0.25),
                "sharpe_ratio": 1.0 + (random.random() * 1.0),
                "max_drawdown": -0.08 - (random.random() * 0.15),
                "win_rate": 0.55 + (random.random() * 0.15),
                "total_trades": 80 + int(random.random() * 120),
                "volatility": 0.12 + (random.random() * 0.1)   # 12-22%
            },
            "breakout": {
                "total_return": 0.2 + (random.random() * 0.4),
                "sharpe_ratio": 0.6 + (random.random() * 1.4),
                "max_drawdown": -0.15 - (random.random() * 0.25),
                "win_rate": 0.4 + (random.random() * 0.2),
                "total_trades": 30 + int(random.random() * 70),
                "volatility": 0.25 + (random.random() * 0.2)   # 25-45%
            },
            "momentum": {
                "total_return": 0.18 + (random.random() * 0.35),
                "sharpe_ratio": 0.9 + (random.random() * 1.1),
                "max_drawdown": -0.12 - (random.random() * 0.18),
                "win_rate": 0.48 + (random.random() * 0.17),
                "total_trades": 40 + int(random.random() * 90),
                "volatility": 0.18 + (random.random() * 0.12)   # 18-30%
            }
        }
        
        # 获取基础结果
        base_result = base_results.get(strategy_type, base_results["trend_following"])
        
        # 根据参数调整结果
        param_adjustments = self._adjust_results_by_parameters(parameters, strategy_type)
        
        # 合并结果
        result = {}
        for key in base_result:
            base_value = base_result[key]
            adjustment = param_adjustments.get(key, 1.0)
            
            if isinstance(base_value, (int, float)):
                # 添加随机噪声
                noise = (random.random() - 0.5) * 0.1  # ±5%
                result[key] = base_value * adjustment * (1 + noise)
            else:
                result[key] = base_value
        
        # 添加额外指标
        initial_capital = backtest_config.get("initial_capital", 10000)
        total_return = result.get("total_return", 0.15)
        
        result.update({
            "initial_capital": initial_capital,
            "final_capital": initial_capital * (1 + total_return),
            "total_commission": initial_capital * total_return * 0.01,  # 假设1%手续费
            "winning_trades": int(result.get("total_trades", 100) * result.get("win_rate", 0.5)),
            "losing_trades": int(result.get("total_trades", 100) * (1 - result.get("win_rate", 0.5))),
            "avg_win": total_return * 0.3 / max(1, result.get("winning_trades", 1)),
            "avg_loss": -total_return * 0.2 / max(1, result.get("losing_trades", 1)),
            "largest_win": total_return * 0.5,
            "largest_loss": -total_return * 0.4
        })
        
        return result
    
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
        """计算性能指标"""
        total_return = backtest_result.get("total_return", 0)
        sharpe_ratio = backtest_result.get("sharpe_ratio", 0)
        max_drawdown = backtest_result.get("max_drawdown", 0)
        win_rate = backtest_result.get("win_rate", 0)
        total_trades = backtest_result.get("total_trades", 0)
            
        # 计算额外指标
        if max_drawdown != 0:
            calmar_ratio = total_return / abs(max_drawdown)
        else:
            calmar_ratio = 0
    
        # 简化的Sortino比率（假设下行波动是总波动的一半）
        sortino_ratio = sharpe_ratio * 1.2 if sharpe_ratio > 0 else 0
    
        avg_win = backtest_result.get("avg_win", 0)
        avg_loss = backtest_result.get("avg_loss", 0)
    
        if avg_loss != 0:
            profit_factor = (avg_win * win_rate) / (abs(avg_loss) * (1 - win_rate))
        else:
            profit_factor = 10 if avg_win > 0 else 0
            
        # 计算波动率（年化）
        # 基于夏普比率反推：sharpe = return / volatility
        # 如果夏普比率存在，volatility = return / sharpe
        # 否则使用经验估计
        volatility = backtest_result.get("volatility", 0)
        if volatility == 0 and sharpe_ratio > 0:
            # 假设年化收益率为 total_return * 2（6个月数据年化）
            annual_return = total_return * 2
            volatility = annual_return / sharpe_ratio if sharpe_ratio > 0 else 0
        elif volatility == 0:
            # 使用经验估计：波动率通常在 15%-50% 范围
            volatility = 0.25  # 默认 25%
    
        return {
            "total_return": round(total_return, 4),
            "annual_return": round(total_return * 2, 4),  # 简化：假设6个月数据
            "sharpe_ratio": round(sharpe_ratio, 3),
            "sortino_ratio": round(sortino_ratio, 3),
            "calmar_ratio": round(calmar_ratio, 3),
            "max_drawdown": round(max_drawdown, 4),
            "max_drawdown_duration": int(abs(max_drawdown) * 100),  # 模拟
            "win_rate": round(win_rate, 3),
            "profit_factor": round(profit_factor, 3),
            "volatility": round(volatility, 4),
            "total_trades": total_trades,
            "winning_trades": backtest_result.get("winning_trades", 0),
            "losing_trades": backtest_result.get("losing_trades", 0),
            "avg_win": round(avg_win, 4),
            "avg_loss": round(avg_loss, 4),
            "largest_win": round(backtest_result.get("largest_win", 0), 4),
            "largest_loss": round(backtest_result.get("largest_loss", 0), 4),
            "expectancy": round(avg_win * win_rate + avg_loss * (1 - win_rate), 4)
        }
    
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