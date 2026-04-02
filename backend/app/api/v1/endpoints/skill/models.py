"""
Skill API请求和响应模型
保持与现有API风格一致
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime

from app.skills.core.models import SkillType, SkillStatus, SkillExecutionStatus


class SkillCreateRequest(BaseModel):
    """创建Skill请求"""
    name: str = Field(..., description="Skill名称", min_length=1, max_length=200)
    description: Optional[str] = Field(None, description="Skill描述")
    skill_type: SkillType = Field(..., description="Skill类型")
    
    # 配置
    input_schema: Dict[str, Any] = Field(default_factory=dict, description="输入格式定义")
    output_schema: Dict[str, Any] = Field(default_factory=dict, description="输出格式定义")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Skill参数")
    dependencies: List[str] = Field(default_factory=list, description="依赖库列表")
    
    # 执行配置
    timeout_seconds: Optional[int] = Field(60, description="超时时间(秒)")
    max_retries: int = Field(3, description="最大重试次数")
    concurrency_limit: int = Field(1, description="并发限制")
    
    # 元数据
    author: Optional[str] = Field(None, description="创建者")
    tags: List[str] = Field(default_factory=list, description="标签列表")
    code_content: Optional[str] = Field(None, description="Skill代码内容")
    implementation_path: Optional[str] = Field(None, description="实现模块路径")


class SkillUpdateRequest(BaseModel):
    """更新Skill请求"""
    name: Optional[str] = Field(None, description="Skill名称")
    description: Optional[str] = Field(None, description="Skill描述")
    status: Optional[SkillStatus] = Field(None, description="Skill状态")
    
    # 配置更新
    input_schema: Optional[Dict[str, Any]] = Field(None, description="输入格式定义")
    output_schema: Optional[Dict[str, Any]] = Field(None, description="输出格式定义")
    parameters: Optional[Dict[str, Any]] = Field(None, description="Skill参数")
    
    # 执行配置更新
    timeout_seconds: Optional[int] = Field(None, description="超时时间(秒)")
    max_retries: Optional[int] = Field(None, description="最大重试次数")
    concurrency_limit: Optional[int] = Field(None, description="并发限制")


class SkillExecuteRequest(BaseModel):
    """执行Skill请求"""
    inputs: Dict[str, Any] = Field(default_factory=dict, description="输入数据")
    parameters: Optional[Dict[str, Any]] = Field(None, description="执行参数")
    context: Optional[Dict[str, Any]] = Field(None, description="执行上下文")
    
    # 执行控制
    timeout_seconds: Optional[int] = Field(None, description="执行超时时间")
    priority: int = Field(5, ge=1, le=10, description="执行优先级(1-10)")


class SkillResponse(BaseModel):
    """Skill响应"""
    skill_id: str = Field(..., description="Skill ID")
    name: str = Field(..., description="Skill名称")
    description: Optional[str] = Field(None, description="Skill描述")
    skill_type: SkillType = Field(..., description="Skill类型")
    version: str = Field(..., description="Skill版本")
    
    # 状态和统计
    status: SkillStatus = Field(..., description="Skill状态")
    execution_count: int = Field(..., description="执行次数")
    success_count: int = Field(..., description="成功次数")
    success_rate: Optional[float] = Field(None, description="成功率")
    avg_execution_time: Optional[float] = Field(None, description="平均执行时间")
    
    # 时间戳
    created_at: Optional[datetime] = Field(None, description="创建时间")
    updated_at: Optional[datetime] = Field(None, description="更新时间")
    last_executed_at: Optional[datetime] = Field(None, description="最后执行时间")
    
    # 元数据
    author: Optional[str] = Field(None, description="创建者")
    tags: List[str] = Field(default_factory=list, description="标签列表")


class SkillExecutionResponse(BaseModel):
    """Skill执行响应"""
    execution_id: str = Field(..., description="执行ID")
    skill_id: str = Field(..., description="Skill ID")
    skill_name: str = Field(..., description="Skill名称")
    
    # 执行状态
    status: SkillExecutionStatus = Field(..., description="执行状态")
    success: bool = Field(..., description="是否成功")
    
    # 结果
    data: Optional[Dict[str, Any]] = Field(None, description="执行结果数据")
    error: Optional[str] = Field(None, description="错误信息")
    
    # 性能指标
    execution_time: Optional[float] = Field(None, description="执行时间(秒)")
    
    # 时间戳
    started_at: Optional[datetime] = Field(None, description="开始时间")
    completed_at: Optional[datetime] = Field(None, description="完成时间")
    skill_version: str = Field(..., description="Skill版本")


class SkillListResponse(BaseModel):
    """Skill列表响应"""
    skills: List[SkillResponse] = Field(..., description="Skill列表")
    total: int = Field(..., description="总数")
    page: int = Field(..., description="页码")
    page_size: int = Field(..., description="每页数量")
    total_pages: int = Field(..., description="总页数")


class SkillExecutionListResponse(BaseModel):
    """Skill执行列表响应"""
    executions: List[SkillExecutionResponse] = Field(..., description="执行记录列表")
    total: int = Field(..., description="总数")
    page: int = Field(..., description="页码")
    page_size: int = Field(..., description="每页数量")
    total_pages: int = Field(..., description="总页数")


class SkillMetricsResponse(BaseModel):
    """Skill指标响应"""
    skill_id: str = Field(..., description="Skill ID")
    skill_name: str = Field(..., description="Skill名称")
    
    # 总体统计
    total_executions: int = Field(..., description="总执行次数")
    successful_executions: int = Field(..., description="成功次数")
    failed_executions: int = Field(..., description="失败次数")
    success_rate: float = Field(..., description="成功率")
    
    # 性能指标
    avg_execution_time: Optional[float] = Field(None, description="平均执行时间")
    min_execution_time: Optional[float] = Field(None, description="最短执行时间")
    max_execution_time: Optional[float] = Field(None, description="最长执行时间")
    
    # 时间范围统计
    today_executions: int = Field(0, description="今日执行次数")
    today_success_rate: Optional[float] = Field(None, description="今日成功率")
    
    # 错误分布
    error_distribution: Optional[Dict[str, int]] = Field(None, description="错误类型分布")


class SkillSearchRequest(BaseModel):
    """Skill搜索请求"""
    name: Optional[str] = Field(None, description="Skill名称关键词")
    skill_type: Optional[SkillType] = Field(None, description="Skill类型")
    status: Optional[SkillStatus] = Field(None, description="Skill状态")
    tags: Optional[List[str]] = Field(None, description="标签列表")
    
    # 分页
    page: int = Field(1, ge=1, description="页码")
    page_size: int = Field(20, ge=1, le=100, description="每页数量")
    
    # 排序
    sort_by: str = Field("created_at", description="排序字段")
    sort_order: str = Field("desc", description="排序顺序")


class SkillHealthCheckResponse(BaseModel):
    """Skill健康检查响应"""
    status: str = Field(..., description="健康状态")
    total_skills: int = Field(..., description="总Skill数")
    active_skills: int = Field(..., description="激活Skill数")
    recent_executions: int = Field(..., description="最近24小时执行次数")
    error_rate: Optional[float] = Field(None, description="错误率")
    
    # 组件状态
    registry_status: str = Field(..., description="注册器状态")
    executor_status: str = Field(..., description="执行器状态")
    storage_status: str = Field(..., description="存储状态")
    
    # 详情
    details: Optional[Dict[str, Any]] = Field(None, description="详细状态信息")


class SkillBulkExecuteRequest(BaseModel):
    """批量执行Skill请求"""
    skill_ids: List[str] = Field(..., description="要执行的Skill ID列表")
    inputs_list: List[Dict[str, Any]] = Field(..., description="输入数据列表")
    
    # 执行配置
    concurrent_limit: int = Field(5, ge=1, le=20, description="并发限制")
    timeout_seconds: Optional[int] = Field(None, description="执行超时时间")


class SkillBulkExecuteResponse(BaseModel):
    """批量执行Skill响应"""
    total_tasks: int = Field(..., description="总任务数")
    completed_tasks: int = Field(..., description="已完成任务数")
    successful_tasks: int = Field(..., description="成功任务数")
    failed_tasks: int = Field(..., description="失败任务数")
    
    # 结果
    results: List[SkillExecutionResponse] = Field(..., description="执行结果列表")
    
    # 性能
    total_execution_time: float = Field(..., description="总执行时间")
    avg_execution_time: float = Field(..., description="平均执行时间")
    
    # 时间戳
    started_at: datetime = Field(..., description="开始时间")
    completed_at: datetime = Field(..., description="完成时间")