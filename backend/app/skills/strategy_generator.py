"""
策略生成Skill
基于市场数据和技术指标生成候选策略
"""

import asyncio
import random
from typing import Any, Dict, List, Optional
from datetime import datetime

import pandas as pd
import numpy as np

from app.skills.core.base import BaseSkill
from app.skills.core.models import SkillDefinition, SkillType


class StrategyGeneratorSkill(BaseSkill):
    """
    策略生成Skill
    
    功能：
    1. 分析市场数据和技术指标
    2. 生成候选交易策略
    3. 评估策略潜力
    4. 输出策略配置
    
    输入：市场数据、技术指标、风险偏好
    输出：候选策略列表、预期表现指标
    """
    
    def __init__(self, skill_definition: SkillDefinition):
        super().__init__(skill_definition)
        self.required_dependencies = ["pandas", "numpy"]
        
        # 策略模板库
        self.strategy_templates = {
            "trend_following": {
                "name": "趋势跟踪策略",
                "description": "基于移动平均线的趋势跟踪策略",
                "indicators": ["ma_fast", "ma_slow"],
                "rules": [
                    "当快线上穿慢线时买入",
                    "当快线下穿慢线时卖出"
                ]
            },
            "mean_reversion": {
                "name": "均值回归策略",
                "description": "基于RSI的均值回归策略",
                "indicators": ["rsi"],
                "rules": [
                    "当RSI低于30时买入（超卖）",
                    "当RSI高于70时卖出（超买）"
                ]
            },
            "breakout": {
                "name": "突破策略",
                "description": "基于布林带的突破策略",
                "indicators": ["boll_upper", "boll_lower", "boll_middle"],
                "rules": [
                    "当价格突破上轨时买入",
                    "当价格跌破下轨时卖出"
                ]
            },
            "momentum": {
                "name": "动量策略",
                "description": "基于MACD的动量策略",
                "indicators": ["macd", "macd_signal"],
                "rules": [
                    "当MACD线上穿信号线时买入",
                    "当MACD线下穿信号线时卖出"
                ]
            }
        }
    
    async def execute(self, inputs: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        执行策略生成
            
        输入格式：
        {
            "market_data": {
                "symbol": "BTCUSDT",
                "interval": "1d",
                "ohlcv": [...],  # OHLCV数据
                "indicators": {  # 技术指标
                    "ma_fast": [...],
                    "ma_slow": [...],
                    "rsi": [...],
                    "boll_upper": [...],
                    "boll_lower": [...],
                    "macd": [...],
                    "macd_signal": [...]
                }
            },
            "constraints": {
                "max_strategies": 10,
                "risk_level": "medium",  # low, medium, high
                "preferred_types": ["trend_following", "mean_reversion"]
            }
        }
            
        输出格式：
        {
            "generated_strategies": [
                {
                    "strategy_id": "strategy_001",
                    "name": "趋势跟踪策略",
                    "type": "trend_following",
                    "description": "基于MA(5, 20)的趋势跟踪策略",
                    "parameters": {...},
                    "code": "...",  # 策略代码字符串
                    "applicable_scenarios": {...},  # 适用场景说明
                    "expected_performance": {
                        "sharpe_ratio": 1.2,
                        "max_drawdown": -0.15,
                        "win_rate": 0.55,
                        "profit_factor": 1.5
                    },
                    "confidence_score": 0.75
                },
                ...
            ],
            "generation_stats": {
                "total_generated": 15,
                "filtered_out": 5,
                "time_taken": 1.23
            }
        }
        """
        start_time = datetime.utcnow()
            
        try:
            # 1. 验证和解析输入
            validation_errors = self._validate_inputs(inputs)
            if validation_errors:
                return self._create_error_result(
                    "input_validation_failed",
                    "输入验证失败",
                    validation_errors,
                    start_time
                )
                
            market_data = inputs.get("market_data", {})
            constraints = inputs.get("constraints", {})
                
            # 2. 分析市场特征
            market_features = await self._analyze_market_features(market_data)
                
            # 3. 生成候选策略
            candidate_strategies = await self._generate_candidate_strategies(
                market_features, 
                constraints
            )
                
            # 检查是否成功生成策略
            if not candidate_strategies:
                return self._create_error_result(
                    "no_strategies_generated",
                    "无法生成有效策略",
                    {"reason": "没有找到适合当前市场条件的策略模板"},
                    start_time
                )
                
            # 4. 评估策略潜力
            evaluated_strategies = await self._evaluate_strategies(
                candidate_strategies,
                market_data,
                market_features
            )
                
            # 5. 筛选和排序
            filtered_strategies = await self._filter_and_rank_strategies(
                evaluated_strategies,
                constraints
            )
                
            # 6. 构建输出
            end_time = datetime.utcnow()
            time_taken = (end_time - start_time).total_seconds()
                
            result = {
                "generated_strategies": filtered_strategies,
                "generation_stats": {
                    "total_generated": len(candidate_strategies),
                    "filtered_out": len(candidate_strategies) - len(filtered_strategies),
                    "time_taken": round(time_taken, 3),
                    "market_features": market_features,
                    "success": True
                }
            }
                
            # 添加执行上下文
            if context:
                result["_context"] = {
                    "execution_id": context.get("execution_id"),
                    "skill_version": self.skill_definition.version,
                    "timestamp": end_time.isoformat()
                }
                
            return result
            
        except ValueError as e:
            return self._create_error_result(
                "value_error",
                "参数值错误",
                {"error": str(e)},
                start_time
            )
        except KeyError as e:
            return self._create_error_result(
                "key_error",
                "缺少必要参数",
                {"missing_key": str(e)},
                start_time
            )
        except Exception as e:
            return self._create_error_result(
                "execution_error",
                "策略生成执行失败",
                {"error": str(e), "error_type": type(e).__name__},
                start_time
            )
        
    def _validate_inputs(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        验证输入参数
            
        Args:
            inputs: 输入数据
                
        Returns:
            验证错误字典，空字典表示验证通过
        """
        errors = {}
            
        # 检查 market_data
        market_data = inputs.get("market_data")
        if market_data is None:
            errors["market_data"] = "缺少必填字段: market_data"
        elif not isinstance(market_data, dict):
            errors["market_data"] = "market_data 必须是字典类型"
        else:
            # 验证 market_data 内容
            symbol = market_data.get("symbol")
            if symbol is not None and not isinstance(symbol, str):
                errors["symbol"] = "symbol 必须是字符串类型"
                
            interval = market_data.get("interval")
            if interval is not None and not isinstance(interval, str):
                errors["interval"] = "interval 必须是字符串类型"
                
            ohlcv = market_data.get("ohlcv")
            if ohlcv is not None and not isinstance(ohlcv, list):
                errors["ohlcv"] = "ohlcv 必须是数组类型"
            
        # 检查 constraints
        constraints = inputs.get("constraints")
        if constraints is not None:
            if not isinstance(constraints, dict):
                errors["constraints"] = "constraints 必须是字典类型"
            else:
                # 验证 max_strategies
                max_strategies = constraints.get("max_strategies")
                if max_strategies is not None:
                    if not isinstance(max_strategies, int) or max_strategies < 1:
                        errors["max_strategies"] = "max_strategies 必须是正整数"
                    elif max_strategies > 50:
                        errors["max_strategies"] = "max_strategies 不能超过 50"
                    
                # 验证 risk_level
                risk_level = constraints.get("risk_level")
                if risk_level is not None:
                    valid_risk_levels = ["low", "medium", "high"]
                    if risk_level not in valid_risk_levels:
                        errors["risk_level"] = f"risk_level 必须是: {valid_risk_levels}"
                    
                # 验证 preferred_types
                preferred_types = constraints.get("preferred_types")
                if preferred_types is not None:
                    if not isinstance(preferred_types, list):
                        errors["preferred_types"] = "preferred_types 必须是数组类型"
                    else:
                        valid_types = set(self.strategy_templates.keys())
                        invalid_types = [t for t in preferred_types if t not in valid_types]
                        if invalid_types:
                            errors["preferred_types"] = f"不支持的策略类型: {invalid_types}，有效类型: {list(valid_types)}"
            
        return errors
        
    def _create_error_result(
        self,
        error_code: str,
        error_message: str,
        error_details: Dict[str, Any],
        start_time: datetime
    ) -> Dict[str, Any]:
        """
        创建错误结果
            
        Args:
            error_code: 错误代码
            error_message: 错误消息
            error_details: 错误详情
            start_time: 开始时间
                
        Returns:
            错误结果字典
        """
        end_time = datetime.utcnow()
        time_taken = (end_time - start_time).total_seconds()
            
        return {
            "generated_strategies": [],
            "generation_stats": {
                "total_generated": 0,
                "filtered_out": 0,
                "time_taken": round(time_taken, 3),
                "success": False,
                "error": {
                    "code": error_code,
                    "message": error_message,
                    "details": error_details
                }
            }
        }
    
    async def _analyze_market_features(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """分析市场特征"""
        features = {
            "trend_strength": 0.5,  # 趋势强度 0-1
            "volatility_level": 0.5,  # 波动率水平 0-1
            "market_regime": "neutral",  # 市场状态: trending, ranging, volatile
            "signal_quality": 0.5,  # 信号质量 0-1
            "indicators_summary": {}
        }
        
        try:
            # 如果有OHLCV数据，进行简单分析
            ohlcv = market_data.get("ohlcv", [])
            if ohlcv and len(ohlcv) > 0:
                # 转换为DataFrame
                df = pd.DataFrame(ohlcv)
                if 'close' in df.columns:
                    # 计算基本特征
                    prices = df['close'].values
                    
                    # 趋势强度（基于价格变化方向一致性）
                    price_changes = np.diff(prices)
                    pos_changes = sum(1 for change in price_changes if change > 0)
                    trend_strength = abs(pos_changes / len(price_changes) - 0.5) * 2
                    features["trend_strength"] = round(trend_strength, 3)
                    
                    # 波动率（基于价格变化幅度）
                    volatility = np.std(price_changes) / np.mean(prices) if np.mean(prices) != 0 else 0
                    features["volatility_level"] = round(min(volatility * 10, 1.0), 3)
                    
                    # 判断市场状态
                    if trend_strength > 0.7:
                        features["market_regime"] = "trending"
                    elif volatility > 0.1:
                        features["market_regime"] = "volatile"
                    else:
                        features["market_regime"] = "ranging"
            
            # 分析技术指标
            indicators = market_data.get("indicators", {})
            if indicators:
                indicator_summary = {}
                for indicator_name, indicator_values in indicators.items():
                    if indicator_values and len(indicator_values) > 0:
                        values = np.array(indicator_values)
                        indicator_summary[indicator_name] = {
                            "current_value": float(values[-1]) if len(values) > 0 else None,
                            "mean": float(np.mean(values)) if len(values) > 0 else None,
                            "std": float(np.std(values)) if len(values) > 0 else None,
                            "trend": "up" if len(values) > 1 and values[-1] > values[-2] else "down"
                        }
                features["indicators_summary"] = indicator_summary
        
        except Exception as e:
            print(f"⚠️ 市场特征分析失败: {e}")
        
        return features
    
    async def _generate_candidate_strategies(
        self, 
        market_features: Dict[str, Any],
        constraints: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """生成候选策略"""
        candidate_strategies = []
        
        # 获取风险等级
        risk_level = constraints.get("risk_level", "medium")
        
        # 验证风险等级
        valid_risk_levels = ["low", "medium", "high"]
        if risk_level not in valid_risk_levels:
            risk_level = "medium"
        
        # 根据市场状态选择策略类型
        market_regime = market_features.get("market_regime", "neutral")
        preferred_types = constraints.get("preferred_types", [])
        
        # 验证策略类型
        if preferred_types:
            # 过滤掉无效的策略类型
            preferred_types = [
                t for t in preferred_types 
                if t in self.strategy_templates
            ]
        
        # 确定要生成的策略类型
        strategy_types = []
        if preferred_types:
            strategy_types = preferred_types
        else:
            # 根据市场状态推荐策略类型
            if market_regime == "trending":
                strategy_types = ["trend_following", "momentum"]
            elif market_regime == "ranging":
                strategy_types = ["mean_reversion", "breakout"]
            elif market_regime == "volatile":
                strategy_types = ["breakout", "trend_following"]
            else:
                strategy_types = list(self.strategy_templates.keys())
        
        # 如果没有有效的策略类型，使用所有模板
        if not strategy_types:
            strategy_types = list(self.strategy_templates.keys())
        
        # 为每种类型生成多个参数变体
        max_strategies = constraints.get("max_strategies", 10)
        strategies_per_type = max(1, max_strategies // len(strategy_types))
        
        for strategy_type in strategy_types:
            if strategy_type not in self.strategy_templates:
                continue
            
            template = self.strategy_templates[strategy_type]
            
            for i in range(strategies_per_type):
                strategy_id = f"strategy_{len(candidate_strategies) + 1:03d}"
                
                # 生成策略参数（基于模板和随机变异）
                base_parameters = self._generate_strategy_parameters(strategy_type, market_features)
                
                # 根据风险等级调整参数
                parameters = self._adjust_params_by_risk_level(
                    base_parameters, risk_level, strategy_type
                )
                
                # 生成策略代码
                strategy_code = self._generate_strategy_code(
                    strategy_type, parameters, template["name"]
                )
                
                # 生成适用场景说明
                applicable_scenarios = self._generate_applicable_scenarios(
                    strategy_type, market_features, risk_level
                )
                
                candidate_strategy = {
                    "strategy_id": strategy_id,
                    "name": template["name"],
                    "type": strategy_type,
                    "description": template["description"],
                    "parameters": parameters,
                    "code": strategy_code,
                    "applicable_scenarios": applicable_scenarios,
                    "template_rules": template["rules"],
                    "generation_metadata": {
                        "based_on_template": strategy_type,
                        "market_regime": market_regime,
                        "risk_level": risk_level,
                        "parameter_variant": i + 1
                    }
                }
                
                candidate_strategies.append(candidate_strategy)
        
        # 如果策略数量不足，补充随机策略
        if len(candidate_strategies) < max_strategies:
            additional_needed = max_strategies - len(candidate_strategies)
            all_types = list(self.strategy_templates.keys())
            
            for i in range(additional_needed):
                strategy_type = random.choice(all_types)
                template = self.strategy_templates[strategy_type]
                
                strategy_id = f"strategy_{len(candidate_strategies) + 1:03d}"
                base_parameters = self._generate_strategy_parameters(strategy_type, market_features)
                
                # 根据风险等级调整参数
                parameters = self._adjust_params_by_risk_level(
                    base_parameters, risk_level, strategy_type
                )
                
                # 生成策略代码
                strategy_code = self._generate_strategy_code(
                    strategy_type, parameters, template["name"]
                )
                
                # 生成适用场景说明
                applicable_scenarios = self._generate_applicable_scenarios(
                    strategy_type, market_features, risk_level
                )
                
                candidate_strategy = {
                    "strategy_id": strategy_id,
                    "name": template["name"],
                    "type": strategy_type,
                    "description": template["description"],
                    "parameters": parameters,
                    "code": strategy_code,
                    "applicable_scenarios": applicable_scenarios,
                    "template_rules": template["rules"],
                    "generation_metadata": {
                        "based_on_template": strategy_type,
                        "market_regime": market_regime,
                        "risk_level": risk_level,
                        "parameter_variant": "random"
                    }
                }
                
                candidate_strategies.append(candidate_strategy)
        
        return candidate_strategies[:max_strategies]
    
    def _generate_strategy_parameters(
        self, 
        strategy_type: str, 
        market_features: Dict[str, Any]
    ) -> Dict[str, Any]:
        """生成策略参数"""
        volatility = market_features.get("volatility_level", 0.5)
        
        if strategy_type == "trend_following":
            # 趋势跟踪策略参数
            base_fast = 5
            base_slow = 20
            
            # 根据波动率调整参数
            volatility_factor = 1 + (volatility - 0.5) * 0.5
            
            return {
                "ma_fast_period": max(2, int(base_fast * volatility_factor)),
                "ma_slow_period": max(10, int(base_slow * volatility_factor)),
                "entry_threshold": round(0.02 * volatility_factor, 3),
                "exit_threshold": round(0.01 * volatility_factor, 3),
                "position_size": 0.1,
                "stop_loss": round(0.05 * volatility_factor, 3)
            }
        
        elif strategy_type == "mean_reversion":
            # 均值回归策略参数
            return {
                "rsi_period": 14,
                "oversold_level": 30,
                "overbought_level": 70,
                "entry_confirmation": 2,  # 连续N期确认
                "exit_on_reversal": True,
                "position_size": 0.08,
                "stop_loss": 0.08
            }
        
        elif strategy_type == "breakout":
            # 突破策略参数
            boll_period = 20
            boll_std = 2.0 * (1 + volatility * 0.5)  # 波动率越高，布林带越宽
            
            return {
                "boll_period": boll_period,
                "boll_std": round(boll_std, 2),
                "breakout_confirmation": 2,
                "retest_entry": True,
                "trailing_stop": True,
                "position_size": 0.12,
                "stop_loss": 0.10
            }
        
        elif strategy_type == "momentum":
            # 动量策略参数
            return {
                "macd_fast": 12,
                "macd_slow": 26,
                "macd_signal": 9,
                "momentum_threshold": 0.01,
                "divergence_confirmation": True,
                "position_size": 0.15,
                "stop_loss": 0.12
            }
        
        else:
            # 默认参数
            return {
                "base_period": 14,
                "sensitivity": 0.5,
                "position_size": 0.1,
                "stop_loss": 0.05
            }
    
    def _adjust_params_by_risk_level(
        self,
        parameters: Dict[str, Any],
        risk_level: str,
        strategy_type: str
    ) -> Dict[str, Any]:
        """
        根据风险等级调整策略参数
            
        Args:
            parameters: 原始策略参数
            risk_level: 风险等级 (low, medium, high)
            strategy_type: 策略类型
                
        Returns:
            调整后的参数
        """
        adjusted = parameters.copy()
            
        # 风险等级对应的调整系数
        risk_adjustments = {
            "low": {
                "position_size_multiplier": 0.5,   # 低风险：仓位减半
                "stop_loss_multiplier": 0.6,       # 止损更紧
                "take_profit_multiplier": 1.5,     # 止盈更宽松
                "max_drawdown_tolerance": 0.10     # 最大回撤容忍度
            },
            "medium": {
                "position_size_multiplier": 1.0,   # 中风险：标准仓位
                "stop_loss_multiplier": 1.0,       # 标准止损
                "take_profit_multiplier": 1.0,     # 标准止盈
                "max_drawdown_tolerance": 0.20     # 最大回撤容忍度
            },
            "high": {
                "position_size_multiplier": 1.5,   # 高风险：仓位增加
                "stop_loss_multiplier": 1.5,       # 止损更宽
                "take_profit_multiplier": 2.0,     # 止盈更高
                "max_drawdown_tolerance": 0.35     # 最大回撤容忍度
            }
        }
            
        adj = risk_adjustments.get(risk_level, risk_adjustments["medium"])
            
        # 调整仓位大小
        if "position_size" in adjusted:
            adjusted["position_size"] = round(
                adjusted["position_size"] * adj["position_size_multiplier"], 4
            )
            # 确保仓位不超过100%
            adjusted["position_size"] = min(adjusted["position_size"], 0.95)
            
        # 调整止损
        if "stop_loss" in adjusted:
            adjusted["stop_loss"] = round(
                adjusted["stop_loss"] * adj["stop_loss_multiplier"], 4
            )
            # 确保止损在合理范围内
            adjusted["stop_loss"] = min(max(adjusted["stop_loss"], 0.01), 0.30)
            
        # 添加风险等级相关的元数据
        adjusted["_risk_config"] = {
            "risk_level": risk_level,
            "max_drawdown_tolerance": adj["max_drawdown_tolerance"],
            "position_size_multiplier": adj["position_size_multiplier"],
            "stop_loss_multiplier": adj["stop_loss_multiplier"]
        }
            
        # 根据策略类型进行特殊调整
        if strategy_type == "trend_following":
            # 趋势跟踪策略：低风险时使用更长周期确认趋势
            if risk_level == "low":
                adjusted["ma_fast_period"] = int(adjusted.get("ma_fast_period", 5) * 1.2)
                adjusted["ma_slow_period"] = int(adjusted.get("ma_slow_period", 20) * 1.2)
            elif risk_level == "high":
                adjusted["entry_threshold"] = adjusted.get("entry_threshold", 0.02) * 0.8
                    
        elif strategy_type == "mean_reversion":
            # 均值回归策略：低风险时使用更极端的超买超卖阈值
            if risk_level == "low":
                adjusted["oversold_level"] = max(adjusted.get("oversold_level", 30) - 5, 20)
                adjusted["overbought_level"] = min(adjusted.get("overbought_level", 70) + 5, 80)
            elif risk_level == "high":
                adjusted["oversold_level"] = min(adjusted.get("oversold_level", 30) + 5, 40)
                adjusted["overbought_level"] = max(adjusted.get("overbought_level", 70) - 5, 60)
                    
        elif strategy_type == "breakout":
            # 突破策略：低风险时使用更宽的布林带
            if risk_level == "low":
                adjusted["boll_std"] = adjusted.get("boll_std", 2.0) * 1.2
            elif risk_level == "high":
                adjusted["boll_std"] = adjusted.get("boll_std", 2.0) * 0.8
                adjusted["breakout_confirmation"] = 1  # 高风险时减少确认周期
                    
        elif strategy_type == "momentum":
            # 动量策略：低风险时使用更保守的阈值
            if risk_level == "low":
                adjusted["momentum_threshold"] = adjusted.get("momentum_threshold", 0.01) * 1.5
            elif risk_level == "high":
                adjusted["momentum_threshold"] = adjusted.get("momentum_threshold", 0.01) * 0.7
            
        return adjusted

    def _generate_strategy_code(
        self,
        strategy_type: str,
        parameters: Dict[str, Any],
        strategy_name: str
    ) -> str:
        """
        生成策略代码字符串
        
        Args:
            strategy_type: 策略类型
            parameters: 策略参数
            strategy_name: 策略名称
            
        Returns:
            可执行的策略代码字符串
        """
        # 提取风险配置（如果有）
        risk_config = parameters.pop("_risk_config", {})
        
        if strategy_type == "trend_following":
            code = self._generate_trend_following_code(parameters, strategy_name)
        elif strategy_type == "mean_reversion":
            code = self._generate_mean_reversion_code(parameters, strategy_name)
        elif strategy_type == "breakout":
            code = self._generate_breakout_code(parameters, strategy_name)
        elif strategy_type == "momentum":
            code = self._generate_momentum_code(parameters, strategy_name)
        else:
            code = self._generate_generic_strategy_code(strategy_type, parameters, strategy_name)
        
        # 恢复风险配置
        if risk_config:
            parameters["_risk_config"] = risk_config
        
        return code
    
    def _generate_trend_following_code(self, params: Dict[str, Any], name: str) -> str:
        """生成趋势跟踪策略代码"""
        fast_period = params.get("ma_fast_period", 5)
        slow_period = params.get("ma_slow_period", 20)
        entry_threshold = params.get("entry_threshold", 0.02)
        exit_threshold = params.get("exit_threshold", 0.01)
        position_size = params.get("position_size", 0.1)
        stop_loss = params.get("stop_loss", 0.05)
        
        return f'''"""
{name} - 趋势跟踪策略
基于移动平均线交叉的趋势跟踪策略
"""

import pandas as pd
import numpy as np
from app.core.strategy import BaseStrategy
from app.models.trading import BarData, OrderRequest, TradeSide, OrderType

class TrendFollowingStrategy(BaseStrategy):
    """趋势跟踪策略实现"""
    
    def __init__(self, strategy_id: str, bus: 'TradingBus'):
        super().__init__(strategy_id, bus)
        self.bars = []
        self.position = 0.0
        self.entry_price = None
        
    async def on_bar(self, bar: BarData):
        self.bars.append(bar)
        
        # 保留足够的历史数据
        if len(self.bars) > 100:
            self.bars.pop(0)
        
        # 需要足够的数据计算指标
        if len(self.bars) < {slow_period}:
            return
        
        # 计算移动平均线
        df = pd.DataFrame([{{'close': b.close}} for b in self.bars])
        fast_ma = df['close'].rolling(window={fast_period}).mean().iloc[-1]
        slow_ma = df['close'].rolling(window={slow_period}).mean().iloc[-1]
        prev_fast_ma = df['close'].rolling(window={fast_period}).mean().iloc[-2]
        prev_slow_ma = df['close'].rolling(window={slow_period}).mean().iloc[-2]
        
        # 买入信号：金叉（快线上穿慢线）
        if prev_fast_ma <= prev_slow_ma and fast_ma > slow_ma:
            if self.position == 0:
                # 检查突破阈值
                price_change_pct = (fast_ma - slow_ma) / slow_ma
                if price_change_pct >= {entry_threshold}:
                    self.log(f"金叉信号触发，快MA={{fast_ma:.2f}}, 慢MA={{slow_ma:.2f}}")
                    order_req = OrderRequest(
                        symbol=bar.symbol,
                        side=TradeSide.BUY,
                        quantity={position_size},
                        price=bar.close,
                        order_type=OrderType.MARKET,
                        strategy_id=self.strategy_id
                    )
                    res = await self.send_order(order_req)
                    if res.status == "FILLED":
                        self.position = res.filled_quantity
                        self.entry_price = bar.close
        
        # 卖出信号：死叉（快线下穿慢线）
        elif prev_fast_ma >= prev_slow_ma and fast_ma < slow_ma:
            if self.position > 0:
                # 检查止损或退出阈值
                if self.entry_price:
                    pnl_pct = (bar.close - self.entry_price) / self.entry_price
                    if pnl_pct <= -{stop_loss} or pnl_pct >= {exit_threshold}:
                        self.log(f"死叉信号触发，平仓盈亏={{pnl_pct*100:.2f}}%")
                        order_req = OrderRequest(
                            symbol=bar.symbol,
                            side=TradeSide.SELL,
                            quantity=self.position,
                            price=bar.close,
                            order_type=OrderType.MARKET,
                            strategy_id=self.strategy_id
                        )
                        res = await self.send_order(order_req)
                        if res.status == "FILLED":
                            self.position = 0
                            self.entry_price = None
    
    async def on_tick(self, tick):
        pass

# 策略参数配置
STRATEGY_PARAMS = {{
    "ma_fast_period": {fast_period},
    "ma_slow_period": {slow_period},
    "entry_threshold": {entry_threshold},
    "exit_threshold": {exit_threshold},
    "position_size": {position_size},
    "stop_loss": {stop_loss}
}}
'''

    def _generate_mean_reversion_code(self, params: Dict[str, Any], name: str) -> str:
        """生成均值回归策略代码"""
        rsi_period = params.get("rsi_period", 14)
        oversold = params.get("oversold_level", 30)
        overbought = params.get("overbought_level", 70)
        position_size = params.get("position_size", 0.08)
        stop_loss = params.get("stop_loss", 0.08)
        
        return f'''"""
{name} - 均值回归策略
基于RSI超买超卖的均值回归策略
"""

import pandas as pd
import numpy as np
from app.core.strategy import BaseStrategy
from app.models.trading import BarData, OrderRequest, TradeSide, OrderType

class MeanReversionStrategy(BaseStrategy):
    """均值回归策略实现"""
    
    def __init__(self, strategy_id: str, bus: 'TradingBus'):
        super().__init__(strategy_id, bus)
        self.bars = []
        self.position = 0.0
        self.entry_price = None
        
    def _calculate_rsi(self, prices: pd.Series, period: int) -> float:
        """计算RSI指标"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi.iloc[-1]
        
    async def on_bar(self, bar: BarData):
        self.bars.append(bar)
        
        if len(self.bars) > 100:
            self.bars.pop(0)
        
        if len(self.bars) < {rsi_period} + 1:
            return
        
        # 计算RSI
        df = pd.DataFrame([{{'close': b.close}} for b in self.bars])
        rsi = self._calculate_rsi(df['close'], {rsi_period})
        
        # 买入信号：RSI低于超卖线
        if rsi < {oversold} and self.position == 0:
            self.log(f"RSI超卖买入信号，RSI={{rsi:.2f}}")
            order_req = OrderRequest(
                symbol=bar.symbol,
                side=TradeSide.BUY,
                quantity={position_size},
                price=bar.close,
                order_type=OrderType.MARKET,
                strategy_id=self.strategy_id
            )
            res = await self.send_order(order_req)
            if res.status == "FILLED":
                self.position = res.filled_quantity
                self.entry_price = bar.close
        
        # 卖出信号：RSI高于超买线或触发止损
        elif rsi > {overbought} and self.position > 0:
            pnl_pct = (bar.close - self.entry_price) / self.entry_price if self.entry_price else 0
            self.log(f"RSI超买卖出信号，RSI={{rsi:.2f}}, 盈亏={{pnl_pct*100:.2f}}%")
            order_req = OrderRequest(
                symbol=bar.symbol,
                side=TradeSide.SELL,
                quantity=self.position,
                price=bar.close,
                order_type=OrderType.MARKET,
                strategy_id=self.strategy_id
            )
            res = await self.send_order(order_req)
            if res.status == "FILLED":
                self.position = 0
                self.entry_price = None
        
        # 止损检查
        if self.position > 0 and self.entry_price:
            pnl_pct = (bar.close - self.entry_price) / self.entry_price
            if pnl_pct <= -{stop_loss}:
                self.log(f"触发止损，平仓盈亏={{pnl_pct*100:.2f}}%")
                order_req = OrderRequest(
                    symbol=bar.symbol,
                    side=TradeSide.SELL,
                    quantity=self.position,
                    price=bar.close,
                    order_type=OrderType.MARKET,
                    strategy_id=self.strategy_id
                )
                res = await self.send_order(order_req)
                if res.status == "FILLED":
                    self.position = 0
                    self.entry_price = None
    
    async def on_tick(self, tick):
        pass

# 策略参数配置
STRATEGY_PARAMS = {{
    "rsi_period": {rsi_period},
    "oversold_level": {oversold},
    "overbought_level": {overbought},
    "position_size": {position_size},
    "stop_loss": {stop_loss}
}}
'''

    def _generate_breakout_code(self, params: Dict[str, Any], name: str) -> str:
        """生成突破策略代码"""
        boll_period = params.get("boll_period", 20)
        boll_std = params.get("boll_std", 2.0)
        position_size = params.get("position_size", 0.12)
        stop_loss = params.get("stop_loss", 0.10)
        
        return f'''"""
{name} - 突破策略
基于布林带的突破策略
"""

import pandas as pd
import numpy as np
from app.core.strategy import BaseStrategy
from app.models.trading import BarData, OrderRequest, TradeSide, OrderType

class BreakoutStrategy(BaseStrategy):
    """突破策略实现"""
    
    def __init__(self, strategy_id: str, bus: 'TradingBus'):
        super().__init__(strategy_id, bus)
        self.bars = []
        self.position = 0.0
        self.entry_price = None
        
    async def on_bar(self, bar: BarData):
        self.bars.append(bar)
        
        if len(self.bars) > 150:
            self.bars.pop(0)
        
        if len(self.bars) < {boll_period}:
            return
        
        # 计算布林带
        df = pd.DataFrame([{{'close': b.close}} for b in self.bars])
        rolling = df['close'].rolling(window={boll_period})
        middle = rolling.mean().iloc[-1]
        std = rolling.std().iloc[-1]
        upper = middle + {boll_std} * std
        lower = middle - {boll_std} * std
        prev_close = self.bars[-2].close if len(self.bars) > 1 else bar.close
        
        # 买入信号：价格突破上轨
        if bar.close > upper and prev_close <= upper and self.position == 0:
            self.log(f"突破上轨买入，价格={{bar.close:.2f}}, 上轨={{upper:.2f}}")
            order_req = OrderRequest(
                symbol=bar.symbol,
                side=TradeSide.BUY,
                quantity={position_size},
                price=bar.close,
                order_type=OrderType.MARKET,
                strategy_id=self.strategy_id
            )
            res = await self.send_order(order_req)
            if res.status == "FILLED":
                self.position = res.filled_quantity
                self.entry_price = bar.close
        
        # 卖出信号：价格跌破下轨或触发止损
        elif self.position > 0:
            should_sell = False
            reason = ""
            
            # 跌破下轨
            if bar.close < lower:
                should_sell = True
                reason = "跌破下轨"
            # 止损
            elif self.entry_price:
                pnl_pct = (bar.close - self.entry_price) / self.entry_price
                if pnl_pct <= -{stop_loss}:
                    should_sell = True
                    reason = f"触发止损，盈亏={{pnl_pct*100:.2f}}%"
            
            if should_sell:
                self.log(f"{{reason}}卖出，价格={{bar.close:.2f}}")
                order_req = OrderRequest(
                    symbol=bar.symbol,
                    side=TradeSide.SELL,
                    quantity=self.position,
                    price=bar.close,
                    order_type=OrderType.MARKET,
                    strategy_id=self.strategy_id
                )
                res = await self.send_order(order_req)
                if res.status == "FILLED":
                    self.position = 0
                    self.entry_price = None
    
    async def on_tick(self, tick):
        pass

# 策略参数配置
STRATEGY_PARAMS = {{
    "boll_period": {boll_period},
    "boll_std": {boll_std},
    "position_size": {position_size},
    "stop_loss": {stop_loss}
}}
'''

    def _generate_momentum_code(self, params: Dict[str, Any], name: str) -> str:
        """生成动量策略代码"""
        macd_fast = params.get("macd_fast", 12)
        macd_slow = params.get("macd_slow", 26)
        macd_signal = params.get("macd_signal", 9)
        position_size = params.get("position_size", 0.15)
        stop_loss = params.get("stop_loss", 0.12)
        
        return f'''"""
{name} - 动量策略
基于MACD的动量策略
"""

import pandas as pd
import numpy as np
from app.core.strategy import BaseStrategy
from app.models.trading import BarData, OrderRequest, TradeSide, OrderType

class MomentumStrategy(BaseStrategy):
    """动量策略实现"""
    
    def __init__(self, strategy_id: str, bus: 'TradingBus'):
        super().__init__(strategy_id, bus)
        self.bars = []
        self.position = 0.0
        self.entry_price = None
        
    def _calculate_macd(self, prices: pd.Series):
        """计算MACD指标"""
        ema_fast = prices.ewm(span={macd_fast}, adjust=False).mean()
        ema_slow = prices.ewm(span={macd_slow}, adjust=False).mean()
        dif = ema_fast - ema_slow
        dea = dif.ewm(span={macd_signal}, adjust=False).mean()
        return dif.iloc[-1], dea.iloc[-1], dif.iloc[-2], dea.iloc[-2]
        
    async def on_bar(self, bar: BarData):
        self.bars.append(bar)
        
        if len(self.bars) > 150:
            self.bars.pop(0)
        
        if len(self.bars) < {macd_slow} + {macd_signal}:
            return
        
        # 计算MACD
        df = pd.DataFrame([{{'close': b.close}} for b in self.bars])
        dif, dea, prev_dif, prev_dea = self._calculate_macd(df['close'])
        
        # 买入信号：MACD金叉
        if prev_dif <= prev_dea and dif > dea and self.position == 0:
            self.log(f"MACD金叉买入，DIF={{dif:.4f}}, DEA={{dea:.4f}}")
            order_req = OrderRequest(
                symbol=bar.symbol,
                side=TradeSide.BUY,
                quantity={position_size},
                price=bar.close,
                order_type=OrderType.MARKET,
                strategy_id=self.strategy_id
            )
            res = await self.send_order(order_req)
            if res.status == "FILLED":
                self.position = res.filled_quantity
                self.entry_price = bar.close
        
        # 卖出信号：MACD死叉或止损
        elif self.position > 0:
            should_sell = False
            reason = ""
            
            # MACD死叉
            if prev_dif >= prev_dea and dif < dea:
                should_sell = True
                reason = "MACD死叉"
            # 止损
            elif self.entry_price:
                pnl_pct = (bar.close - self.entry_price) / self.entry_price
                if pnl_pct <= -{stop_loss}:
                    should_sell = True
                    reason = f"触发止损，盈亏={{pnl_pct*100:.2f}}%"
            
            if should_sell:
                self.log(f"{{reason}}卖出，价格={{bar.close:.2f}}")
                order_req = OrderRequest(
                    symbol=bar.symbol,
                    side=TradeSide.SELL,
                    quantity=self.position,
                    price=bar.close,
                    order_type=OrderType.MARKET,
                    strategy_id=self.strategy_id
                )
                res = await self.send_order(order_req)
                if res.status == "FILLED":
                    self.position = 0
                    self.entry_price = None
    
    async def on_tick(self, tick):
        pass

# 策略参数配置
STRATEGY_PARAMS = {{
    "macd_fast": {macd_fast},
    "macd_slow": {macd_slow},
    "macd_signal": {macd_signal},
    "position_size": {position_size},
    "stop_loss": {stop_loss}
}}
'''

    def _generate_generic_strategy_code(self, strategy_type: str, params: Dict[str, Any], name: str) -> str:
        """生成通用策略代码模板"""
        position_size = params.get("position_size", 0.1)
        stop_loss = params.get("stop_loss", 0.05)
        
        return f'''"""
{name} - {strategy_type}策略
通用策略模板
"""

import pandas as pd
import numpy as np
from app.core.strategy import BaseStrategy
from app.models.trading import BarData, OrderRequest, TradeSide, OrderType

class GenericStrategy(BaseStrategy):
    """通用策略实现"""
    
    def __init__(self, strategy_id: str, bus: 'TradingBus'):
        super().__init__(strategy_id, bus)
        self.bars = []
        self.position = 0.0
        self.entry_price = None
        
    async def on_bar(self, bar: BarData):
        self.bars.append(bar)
        
        if len(self.bars) > 100:
            self.bars.pop(0)
        
        # TODO: 实现具体的策略逻辑
        # 在此处添加买入/卖出信号判断
        
        # 止损检查
        if self.position > 0 and self.entry_price:
            pnl_pct = (bar.close - self.entry_price) / self.entry_price
            if pnl_pct <= -{stop_loss}:
                self.log(f"触发止损，平仓盈亏={{pnl_pct*100:.2f}}%")
                order_req = OrderRequest(
                    symbol=bar.symbol,
                    side=TradeSide.SELL,
                    quantity=self.position,
                    price=bar.close,
                    order_type=OrderType.MARKET,
                    strategy_id=self.strategy_id
                )
                res = await self.send_order(order_req)
                if res.status == "FILLED":
                    self.position = 0
                    self.entry_price = None
    
    async def on_tick(self, tick):
        pass

# 策略参数配置
STRATEGY_PARAMS = {{
    "strategy_type": "{strategy_type}",
    "position_size": {position_size},
    "stop_loss": {stop_loss}
}}
'''

    def _generate_applicable_scenarios(
        self,
        strategy_type: str,
        market_features: Dict[str, Any],
        risk_level: str
    ) -> Dict[str, Any]:
        """
        生成策略适用场景说明
        
        Args:
            strategy_type: 策略类型
            market_features: 市场特征
            risk_level: 风险等级
            
        Returns:
            适用场景说明字典
        """
        market_regime = market_features.get("market_regime", "neutral")
        volatility = market_features.get("volatility_level", 0.5)
        trend_strength = market_features.get("trend_strength", 0.5)
        
        # 基础场景定义
        base_scenarios = {
            "trend_following": {
                "ideal_market_regime": ["trending"],
                "ideal_volatility": "medium",
                "time_horizon": "中长线",
                "market_condition": "趋势明确、波动适中",
                "risk_characteristics": "追涨杀跌，可能错过反转",
                "recommended_symbols": ["主流币种", "高流动性品种"],
                "avoid_conditions": ["震荡盘整", "突发新闻市"]
            },
            "mean_reversion": {
                "ideal_market_regime": ["ranging", "neutral"],
                "ideal_volatility": "low",
                "time_horizon": "短线",
                "market_condition": "震荡盘整、有明确支撑阻力",
                "risk_characteristics": "逆势操作，可能被套",
                "recommended_symbols": ["高波动币种", "有明确区间的品种"],
                "avoid_conditions": ["强趋势", "单边行情"]
            },
            "breakout": {
                "ideal_market_regime": ["volatile", "trending"],
                "ideal_volatility": "high",
                "time_horizon": "中短线",
                "market_condition": "波动率放大、突破关键位",
                "risk_characteristics": "假突破风险，需要确认",
                "recommended_symbols": ["高波动币种", "创新高品种"],
                "avoid_conditions": ["低波动盘整", "市场清淡"]
            },
            "momentum": {
                "ideal_market_regime": ["trending", "volatile"],
                "ideal_volatility": "medium-high",
                "time_horizon": "中线",
                "market_condition": "动量强劲、趋势延续",
                "risk_characteristics": "追高买入，需要及时止盈",
                "recommended_symbols": ["热点币种", "量价齐升品种"],
                "avoid_conditions": ["趋势末端", "量能萎缩"]
            }
        }
        
        # 获取基础场景配置
        scenario = base_scenarios.get(strategy_type, {
            "ideal_market_regime": ["any"],
            "ideal_volatility": "medium",
            "time_horizon": "中线",
            "market_condition": "通用",
            "risk_characteristics": "标准风险",
            "recommended_symbols": ["流动性好的品种"],
            "avoid_conditions": []
        }).copy()
        
        # 添加当前市场匹配度分析
        regime_match = market_regime in scenario.get("ideal_market_regime", [])
        
        volatility_match = False
        ideal_vol = scenario.get("ideal_volatility", "medium")
        if ideal_vol == "low" and volatility < 0.3:
            volatility_match = True
        elif ideal_vol == "medium" and 0.3 <= volatility <= 0.7:
            volatility_match = True
        elif ideal_vol == "high" and volatility > 0.7:
            volatility_match = True
        elif ideal_vol == "medium-high" and volatility >= 0.5:
            volatility_match = True
        
        # 生成适应性评分
        adaptability_score = 0.0
        if regime_match:
            adaptability_score += 0.5
        if volatility_match:
            adaptability_score += 0.3
        if trend_strength > 0.6 and strategy_type in ["trend_following", "momentum"]:
            adaptability_score += 0.2
        elif trend_strength < 0.4 and strategy_type in ["mean_reversion"]:
            adaptability_score += 0.2
        
        scenario["current_market_match"] = {
            "regime_match": regime_match,
            "volatility_match": volatility_match,
            "adaptability_score": round(adaptability_score, 3),
            "current_regime": market_regime,
            "current_volatility": volatility
        }
        
        # 根据风险等级添加建议
        risk_recommendations = {
            "low": {
                "position_sizing": "建议使用固定小额仓位",
                "holding_period": "建议延长持仓周期以减少噪音影响",
                "exit_strategy": "设置较紧止损，及时止盈"
            },
            "medium": {
                "position_sizing": "标准仓位管理",
                "holding_period": "按照信号正常持仓",
                "exit_strategy": "遵循策略信号出场"
            },
            "high": {
                "position_sizing": "可适当放大仓位",
                "holding_period": "可缩短持仓周期捕捉更多机会",
                "exit_strategy": "可设置较宽止损给予更多波动空间"
            }
        }
        
        scenario["risk_recommendations"] = risk_recommendations.get(risk_level, risk_recommendations["medium"])
        scenario["risk_level"] = risk_level
        
        return scenario

    async def _evaluate_strategies(
        self, 
        strategies: List[Dict[str, Any]],
        market_data: Dict[str, Any],
        market_features: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """评估策略潜力（简化评估）"""
        evaluated_strategies = []
        
        for strategy in strategies:
            strategy_type = strategy["type"]
            parameters = strategy["parameters"]
            
            # 简化评估逻辑
            # 实际项目中应运行回测或模拟
            confidence_score = self._calculate_confidence_score(
                strategy_type, 
                parameters, 
                market_features
            )
            
            # 生成预期表现指标（模拟）
            expected_performance = self._simulate_expected_performance(
                strategy_type,
                parameters,
                market_features
            )
            
            evaluated_strategy = {
                **strategy,
                "expected_performance": expected_performance,
                "confidence_score": confidence_score,
                "evaluation_notes": self._get_evaluation_notes(strategy_type, market_features)
            }
            
            evaluated_strategies.append(evaluated_strategy)
        
        return evaluated_strategies
    
    def _calculate_confidence_score(
        self, 
        strategy_type: str, 
        parameters: Dict[str, Any],
        market_features: Dict[str, Any]
    ) -> float:
        """计算策略置信度得分"""
        base_score = 0.5
        
        # 根据市场状态调整
        market_regime = market_features.get("market_regime", "neutral")
        
        regime_bonus = {
            "trending": {"trend_following": 0.3, "momentum": 0.2, "mean_reversion": -0.1, "breakout": 0.1},
            "ranging": {"mean_reversion": 0.3, "breakout": 0.2, "trend_following": -0.1, "momentum": -0.1},
            "volatile": {"breakout": 0.3, "trend_following": 0.1, "momentum": 0.1, "mean_reversion": -0.2}
        }
        
        if market_regime in regime_bonus:
            bonus = regime_bonus[market_regime].get(strategy_type, 0.0)
            base_score += bonus
        
        # 根据参数合理性调整
        volatility = market_features.get("volatility_level", 0.5)
        
        if strategy_type == "trend_following":
            fast_period = parameters.get("ma_fast_period", 5)
            slow_period = parameters.get("ma_slow_period", 20)
            
            # 检查参数合理性
            if slow_period > fast_period * 3:
                base_score -= 0.1
            elif slow_period <= fast_period:
                base_score -= 0.2
        
        # 确保得分在合理范围内
        confidence_score = max(0.1, min(0.95, base_score))
        
        return round(confidence_score, 3)
    
    def _simulate_expected_performance(
        self,
        strategy_type: str,
        parameters: Dict[str, Any],
        market_features: Dict[str, Any]
    ) -> Dict[str, Any]:
        """模拟预期表现指标"""
        base_sharpe = 0.8
        base_drawdown = -0.2
        base_win_rate = 0.45
        base_profit_factor = 1.2
        
        # 根据策略类型和市场状态调整
        market_regime = market_features.get("market_regime", "neutral")
        volatility = market_features.get("volatility_level", 0.5)
        
        # 类型调整系数
        type_adjustments = {
            "trend_following": {"sharpe": 0.3, "drawdown": -0.05, "win_rate": 0.1, "profit_factor": 0.3},
            "mean_reversion": {"sharpe": 0.2, "drawdown": -0.1, "win_rate": 0.15, "profit_factor": 0.2},
            "breakout": {"sharpe": 0.4, "drawdown": -0.15, "win_rate": 0.05, "profit_factor": 0.4},
            "momentum": {"sharpe": 0.35, "drawdown": -0.12, "win_rate": 0.08, "profit_factor": 0.35}
        }
        
        adjustments = type_adjustments.get(strategy_type, {"sharpe": 0, "drawdown": 0, "win_rate": 0, "profit_factor": 0})
        
        # 市场状态调整
        regime_multiplier = {
            "trending": 1.2,
            "ranging": 0.9,
            "volatile": 0.8,
            "neutral": 1.0
        }
        
        multiplier = regime_multiplier.get(market_regime, 1.0)
        
        # 波动率调整（高波动率通常导致更差的表现）
        volatility_penalty = 1.0 - (volatility * 0.3)
        
        # 计算最终指标
        sharpe_ratio = (base_sharpe + adjustments["sharpe"]) * multiplier * volatility_penalty
        max_drawdown = (base_drawdown + adjustments["drawdown"]) * (1.0 / multiplier) * (1.0 / volatility_penalty)
        win_rate = (base_win_rate + adjustments["win_rate"]) * multiplier * volatility_penalty
        profit_factor = (base_profit_factor + adjustments["profit_factor"]) * multiplier * volatility_penalty
        
        # 添加随机噪声（±10%）
        import random
        sharpe_ratio *= (0.9 + random.random() * 0.2)
        max_drawdown *= (0.9 + random.random() * 0.2)
        win_rate *= (0.9 + random.random() * 0.2)
        profit_factor *= (0.9 + random.random() * 0.2)
        
        return {
            "sharpe_ratio": round(max(0, sharpe_ratio), 3),
            "max_drawdown": round(min(-0.01, max_drawdown), 3),
            "win_rate": round(min(0.7, max(0.3, win_rate)), 3),
            "profit_factor": round(max(1.0, profit_factor), 3),
            "estimated_annual_return": round(sharpe_ratio * 0.1, 3)  # 简化估算
        }
    
    def _get_evaluation_notes(self, strategy_type: str, market_features: Dict[str, Any]) -> str:
        """获取策略评估说明"""
        market_regime = market_features.get("market_regime", "neutral")
        
        notes = {
            "trend_following": "适合趋势明显的市场",
            "mean_reversion": "适合震荡盘整的市场",
            "breakout": "适合波动率较高的市场",
            "momentum": "适合有明显动量效应的市场"
        }
        
        base_note = notes.get(strategy_type, "通用策略类型")
        
        if market_regime == "trending" and strategy_type == "trend_following":
            return f"{base_note}，当前市场处于趋势状态，预期表现良好"
        elif market_regime == "ranging" and strategy_type == "mean_reversion":
            return f"{base_note}，当前市场处于盘整状态，预期表现良好"
        else:
            return f"{base_note}，需注意当前市场状态为{market_regime}的适应性"
    
    async def _filter_and_rank_strategies(
        self, 
        strategies: List[Dict[str, Any]],
        constraints: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """筛选和排序策略"""
        risk_level = constraints.get("risk_level", "medium")
        
        # 风险等级过滤
        risk_filters = {
            "low": lambda s: s["expected_performance"]["max_drawdown"] > -0.15,
            "medium": lambda s: s["expected_performance"]["max_drawdown"] > -0.25,
            "high": lambda s: True  # 不过滤
        }
        
        filter_func = risk_filters.get(risk_level, risk_filters["medium"])
        filtered_strategies = [s for s in strategies if filter_func(s)]
        
        # 按夏普比率排序（降序）
        filtered_strategies.sort(
            key=lambda s: s["expected_performance"]["sharpe_ratio"],
            reverse=True
        )
        
        # 限制数量
        max_strategies = constraints.get("max_strategies", 10)
        return filtered_strategies[:max_strategies]