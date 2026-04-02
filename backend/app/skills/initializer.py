"""
Skill系统初始化器
负责Skill系统的启动、注册和配置
"""

import asyncio
from typing import Dict, Any, Optional

from app.skills.core.base import SkillRegistry
from app.skills.core.models import SkillDefinition, SkillType, SkillStatus
from app.skills.strategy_generator import StrategyGeneratorSkill
from app.skills.backtest_evaluator import BacktestEvaluatorSkill


class SkillSystemInitializer:
    """Skill系统初始化器"""
    
    def __init__(self, registry: SkillRegistry):
        self.registry = registry
        self._initialized = False
        
    async def initialize(self) -> bool:
        """初始化Skill系统"""
        if self._initialized:
            print("[OK] Skill系统已初始化")
            return True
        
        try:
            print("[INIT] 初始化Skill系统...")
            
            # 1. 注册策略生成Skill
            await self._register_strategy_generator()
            
            # 2. 注册回测评估Skill
            await self._register_backtest_evaluator()
            
            # 3. 打印注册统计
            self._print_registration_stats()
            
            self._initialized = True
            print("[OK] Skill系统初始化完成")
            return True
            
        except Exception as e:
            print(f"[ERROR] Skill系统初始化失败: {e}")
            return False
    
    async def _register_strategy_generator(self) -> None:
        """注册策略生成Skill"""
        skill_id = "skill_strategy_generator_v1"
        skill_name = "策略生成器"
        
        skill_definition = SkillDefinition(
            skill_id=skill_id,
            name=skill_name,
            description="基于市场数据和技术指标生成候选交易策略",
            skill_type=SkillType.STRATEGY_GENERATOR,
            version="1.0.0",
            
            # 输入格式定义
            input_schema={
                "type": "object",
                "required": ["market_data"],
                "properties": {
                    "market_data": {
                        "type": "object",
                        "description": "市场数据",
                        "required": ["symbol", "interval", "ohlcv"],
                        "properties": {
                            "symbol": {"type": "string", "description": "交易对"},
                            "interval": {"type": "string", "description": "时间周期"},
                            "ohlcv": {"type": "array", "description": "OHLCV数据"},
                            "indicators": {"type": "object", "description": "技术指标"}
                        }
                    },
                    "constraints": {
                        "type": "object",
                        "description": "生成约束",
                        "properties": {
                            "max_strategies": {"type": "integer", "minimum": 1, "maximum": 50},
                            "risk_level": {"type": "string", "enum": ["low", "medium", "high"]},
                            "preferred_types": {"type": "array", "items": {"type": "string"}}
                        }
                    }
                }
            },
            
            # 输出格式定义
            output_schema={
                "type": "object",
                "required": ["generated_strategies"],
                "properties": {
                    "generated_strategies": {
                        "type": "array",
                        "description": "生成的策略列表",
                        "items": {
                            "type": "object",
                            "properties": {
                                "strategy_id": {"type": "string"},
                                "name": {"type": "string"},
                                "type": {"type": "string"},
                                "description": {"type": "string"},
                                "parameters": {"type": "object"},
                                "expected_performance": {"type": "object"},
                                "confidence_score": {"type": "number"}
                            }
                        }
                    },
                    "generation_stats": {
                        "type": "object",
                        "description": "生成统计信息"
                    }
                }
            },
            
            # 参数配置
            parameters={
                "default_max_strategies": 10,
                "default_risk_level": "medium",
                "market_analysis_depth": "normal"
            },
            
            # 依赖
            dependencies=["pandas", "numpy"],
            
            # 执行配置
            timeout_seconds=30,
            max_retries=3,
            concurrency_limit=2,
            
            # 元数据
            author="QuantAgent Team",
            tags=["strategy", "generation", "analysis", "quantitative"],
            status=SkillStatus.ACTIVE,
            created_at=None,
            updated_at=None
        )
        
        self.registry.register(StrategyGeneratorSkill, skill_definition)
        print(f"   [REG] 注册: {skill_name} ({skill_id})")
    
    async def _register_backtest_evaluator(self) -> None:
        """注册回测评估Skill"""
        skill_id = "skill_backtest_evaluator_v1"
        skill_name = "回测评估器"
        
        skill_definition = SkillDefinition(
            skill_id=skill_id,
            name=skill_name,
            description="评估策略在历史数据上的表现，计算性能指标和风险评估",
            skill_type=SkillType.OPTIMIZATION_EVALUATOR,
            version="1.0.0",
            
            # 输入格式定义
            input_schema={
                "type": "object",
                "required": ["strategies", "market_data"],
                "properties": {
                    "strategies": {
                        "type": "array",
                        "description": "策略配置列表",
                        "items": {
                            "type": "object",
                            "required": ["strategy_id"],
                            "properties": {
                                "strategy_id": {"type": "string"},
                                "name": {"type": "string"},
                                "type": {"type": "string"},
                                "parameters": {"type": "object"}
                            }
                        }
                    },
                    "market_data": {
                        "type": "object",
                        "description": "市场数据",
                        "required": ["symbol", "interval", "ohlcv"],
                        "properties": {
                            "symbol": {"type": "string"},
                            "interval": {"type": "string"},
                            "ohlcv": {"type": "array"},
                            "indicators": {"type": "object"}
                        }
                    },
                    "backtest_config": {
                        "type": "object",
                        "description": "回测配置",
                        "properties": {
                            "initial_capital": {"type": "number", "minimum": 1},
                            "commission_rate": {"type": "number", "minimum": 0},
                            "slippage": {"type": "number", "minimum": 0},
                            "position_size": {"type": "number", "minimum": 0, "maximum": 1}
                        }
                    },
                    "evaluation_config": {
                        "type": "object",
                        "description": "评估配置",
                        "properties": {
                            "include_metrics": {"type": "array", "items": {"type": "string"}},
                            "risk_assessment": {"type": "boolean"},
                            "comparative_analysis": {"type": "boolean"},
                            "generate_report": {"type": "boolean"}
                        }
                    }
                }
            },
            
            # 输出格式定义
            output_schema={
                "type": "object",
                "required": ["evaluation_results"],
                "properties": {
                    "evaluation_results": {
                        "type": "array",
                        "description": "评估结果列表",
                        "items": {
                            "type": "object",
                            "properties": {
                                "strategy_id": {"type": "string"},
                                "strategy_name": {"type": "string"},
                                "backtest_performance": {"type": "object"},
                                "risk_assessment": {"type": "object"},
                                "ranking": {"type": "object"}
                            }
                        }
                    },
                    "comparative_analysis": {
                        "type": "object",
                        "description": "比较分析结果"
                    },
                    "evaluation_summary": {
                        "type": "object",
                        "description": "评估摘要"
                    }
                }
            },
            
            # 参数配置
            parameters={
                "default_commission_rate": 0.001,
                "default_slippage": 0.001,
                "default_position_size": 0.1,
                "metric_weights": {
                    "sharpe_ratio": 0.25,
                    "max_drawdown": 0.20,
                    "total_return": 0.15
                }
            },
            
            # 依赖
            dependencies=["pandas", "numpy"],
            
            # 执行配置
            timeout_seconds=60,
            max_retries=3,
            concurrency_limit=1,
            
            # 元数据
            author="QuantAgent Team",
            tags=["backtest", "evaluation", "performance", "risk", "quantitative"],
            status=SkillStatus.ACTIVE,
            created_at=None,
            updated_at=None
        )
        
        self.registry.register(BacktestEvaluatorSkill, skill_definition)
        print(f"   [REG] 注册: {skill_name} ({skill_id})")
    
    def _print_registration_stats(self) -> None:
        """打印注册统计信息"""
        total_skills = self.registry.count_skills()
        skill_types = {}
        
        for skill_type in SkillType:
            count = self.registry.count_skills(skill_type)
            if count > 0:
                skill_types[skill_type.value] = count
        
        print(f"[STATS] Skill注册统计:")
        print(f"   总Skill数: {total_skills}")
        for skill_type, count in skill_types.items():
            print(f"   {skill_type}: {count}")
        
        if total_skills == 0:
            print("[WARN] 警告: 没有注册任何Skill")
    
    async def get_system_status(self) -> Dict[str, Any]:
        """获取系统状态"""
        return {
            "initialized": self._initialized,
            "total_skills": self.registry.count_skills(),
            "skill_types": {
                skill_type.value: self.registry.count_skills(skill_type)
                for skill_type in SkillType
            },
            "available_skills": [
                {
                    "skill_id": skill_def.skill_id,
                    "name": skill_def.name,
                    "type": skill_def.skill_type,
                    "version": skill_def.version
                }
                for skill_def in self.registry.list_skills()
            ]
        }


# 全局Skill系统实例
_skill_registry = None
_skill_initializer = None


def get_skill_registry() -> SkillRegistry:
    """获取全局Skill注册器（单例）"""
    global _skill_registry
    if _skill_registry is None:
        _skill_registry = SkillRegistry()
    return _skill_registry


def get_skill_initializer() -> SkillSystemInitializer:
    """获取Skill系统初始化器（单例）"""
    global _skill_initializer
    if _skill_initializer is None:
        registry = get_skill_registry()
        _skill_initializer = SkillSystemInitializer(registry)
    return _skill_initializer


async def initialize_skill_system() -> bool:
    """初始化整个Skill系统"""
    initializer = get_skill_initializer()
    return await initializer.initialize()