"""
智能体Skill核心模型定义
与现有Pydantic + SQLAlchemy架构保持一致性
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Type
from pydantic import BaseModel, Field, validator
from datetime import datetime

class SkillType(str, Enum):
    """Skill类型枚举"""
    STRATEGY_GENERATOR = "strategy_generator"      # 策略生成器
    OPTIMIZATION_EVALUATOR = "optimization_evaluator"  # 优化评估器
    MARKET_ANALYZER = "market_analyzer"            # 市场分析器
    RISK_ASSESSOR = "risk_assessor"                # 风险评估器
    FEATURE_ENGINEER = "feature_engineer"          # 特征工程器
    DATA_PROCESSOR = "data_processor"              # 数据处理器
    CUSTOM = "custom"                              # 自定义类型

class SkillStatus(str, Enum):
    """Skill状态枚举"""
    ACTIVE = "active"          # 激活状态
    INACTIVE = "inactive"      # 未激活
    DEPRECATED = "deprecated"  # 已弃用
    EXPERIMENTAL = "experimental"  # 实验性

class SkillExecutionStatus(str, Enum):
    """Skill执行状态"""
    PENDING = "pending"        # 等待执行
    RUNNING = "running"        # 执行中
    COMPLETED = "completed"    # 执行完成
    FAILED = "failed"          # 执行失败
    CANCELLED = "cancelled"    # 已取消

class SkillBase(BaseModel):
    """Skill基础模型"""
    name: str = Field(..., description="Skill名称", min_length=1, max_length=200)
    description: Optional[str] = Field(None, description="Skill详细描述")
    skill_type: SkillType = Field(..., description="Skill类型")
    version: str = Field("1.0.0", description="Skill版本")
    
    class Config:
        use_enum_values = True
        schema_extra = {
            "example": {
                "name": "趋势策略生成器",
                "description": "基于MA和RSI指标生成趋势跟踪策略",
                "skill_type": "strategy_generator",
                "version": "1.0.0"
            }
        }

class SkillConfig(SkillBase):
    """Skill配置模型"""
    input_schema: Dict[str, Any] = Field(default_factory=dict, description="输入数据格式定义")
    output_schema: Dict[str, Any] = Field(default_factory=dict, description="输出数据格式定义")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Skill参数配置")
    dependencies: List[str] = Field(default_factory=list, description="依赖库列表")
    
    # 执行配置
    timeout_seconds: Optional[int] = Field(60, description="超时时间(秒)")
    max_retries: int = Field(3, description="最大重试次数")
    concurrency_limit: int = Field(1, description="并发限制")
    
    @validator("timeout_seconds")
    def validate_timeout(cls, v):
        if v is not None and v <= 0:
            raise ValueError("超时时间必须大于0")
        return v

class SkillDefinition(SkillConfig):
    """Skill定义完整模型"""
    skill_id: str = Field(..., description="Skill唯一标识符", min_length=1, max_length=100)
    implementation_path: Optional[str] = Field(None, description="实现模块路径")
    code_content: Optional[str] = Field(None, description="Skill代码内容")
    
    # 元数据
    author: Optional[str] = Field(None, description="创建者")
    tags: List[str] = Field(default_factory=list, description="标签列表")
    status: SkillStatus = Field(SkillStatus.ACTIVE, description="Skill状态")
    
    # 性能统计
    execution_count: int = Field(0, description="执行次数")
    success_count: int = Field(0, description="成功次数")
    avg_execution_time: Optional[float] = Field(None, description="平均执行时间")
    
    # 时间戳
    created_at: Optional[datetime] = Field(None, description="创建时间")
    updated_at: Optional[datetime] = Field(None, description="更新时间")

class SkillExecutionRequest(BaseModel):
    """Skill执行请求模型"""
    skill_id: str = Field(..., description="要执行的Skill ID")
    inputs: Dict[str, Any] = Field(default_factory=dict, description="输入数据")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="执行参数")
    context: Optional[Dict[str, Any]] = Field(None, description="执行上下文")

class SkillExecutionResult(BaseModel):
    """Skill执行结果模型"""
    execution_id: str = Field(..., description="执行ID")
    skill_id: str = Field(..., description="Skill ID")
    
    # 执行状态
    status: SkillExecutionStatus = Field(..., description="执行状态")
    success: bool = Field(..., description="是否成功")
    
    # 结果数据
    data: Optional[Dict[str, Any]] = Field(None, description="执行结果数据")
    error: Optional[str] = Field(None, description="错误信息")
    error_details: Optional[Dict[str, Any]] = Field(None, description="错误详情")
    
    # 性能指标
    execution_time: Optional[float] = Field(None, description="执行时间(秒)")
    started_at: Optional[datetime] = Field(None, description="开始时间")
    completed_at: Optional[datetime] = Field(None, description="完成时间")
    
    # 元数据
    skill_version: str = Field(..., description="Skill版本")
    inputs_hash: Optional[str] = Field(None, description="输入数据哈希")

class SkillMetrics(BaseModel):
    """Skill性能指标模型"""
    skill_id: str = Field(..., description="Skill ID")
    period_start: datetime = Field(..., description="统计开始时间")
    period_end: datetime = Field(..., description="统计结束时间")
    
    # 执行统计
    total_executions: int = Field(0, description="总执行次数")
    successful_executions: int = Field(0, description="成功次数")
    failed_executions: int = Field(0, description="失败次数")
    
    # 性能指标
    avg_execution_time: Optional[float] = Field(None, description="平均执行时间")
    min_execution_time: Optional[float] = Field(None, description="最短执行时间")
    max_execution_time: Optional[float] = Field(None, description="最长执行时间")
    
    # 成功率
    success_rate: Optional[float] = Field(None, description="成功率")
    
    @validator("success_rate", always=True)
    def calculate_success_rate(cls, v, values):
        if "total_executions" in values and values["total_executions"] > 0:
            return round(values["successful_executions"] / values["total_executions"], 4)
        return None