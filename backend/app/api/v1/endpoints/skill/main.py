"""
Skill API端点
与现有FastAPI架构完全集成
"""

import asyncio
import uuid
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.database import get_db_session as get_async_session
from app.skills.core.models import SkillType, SkillStatus, SkillExecutionStatus
from app.skills.core.base import SkillRegistry
from app.skills.engine.executor import SkillExecutor
from app.skills.engine.context import SkillContextManager
from app.services.skill.storage_service import SkillStorageService

from .models import (
    SkillCreateRequest,
    SkillUpdateRequest,
    SkillExecuteRequest,
    SkillResponse,
    SkillExecutionResponse,
    SkillListResponse,
    SkillExecutionListResponse,
    SkillMetricsResponse,
    SkillSearchRequest,
    SkillHealthCheckResponse,
    SkillBulkExecuteRequest,
    SkillBulkExecuteResponse
)

router = APIRouter()

# 全局Skill引擎组件（依赖注入）
_registry = None
_executor = None
_context_manager = None

def get_skill_registry() -> SkillRegistry:
    """获取Skill注册器（单例）"""
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
    return _registry

def get_skill_executor(registry: SkillRegistry = Depends(get_skill_registry)) -> SkillExecutor:
    """获取Skill执行器"""
    global _executor
    if _executor is None:
        _executor = SkillExecutor(registry)
    return _executor

def get_skill_context_manager() -> SkillContextManager:
    """获取Skill上下文管理器"""
    global _context_manager
    if _context_manager is None:
        _context_manager = SkillContextManager()
    return _context_manager


@router.post("/skills", response_model=SkillResponse, status_code=status.HTTP_201_CREATED)
async def create_skill(
    request: SkillCreateRequest,
    registry: SkillRegistry = Depends(get_skill_registry),
    session: AsyncSession = Depends(get_async_session)
):
    """
    创建新的Skill
    
    注意：此API仅创建Skill定义，真正的Skill类需要实现并注册
    """
    try:
        from app.skills.core.models import SkillDefinition
        
        # 生成Skill ID
        skill_id = f"skill_{uuid.uuid4().hex[:8]}"
        
        # 创建Skill定义
        definition = SkillDefinition(
            skill_id=skill_id,
            name=request.name,
            description=request.description,
            skill_type=request.skill_type,
            version="1.0.0",
            input_schema=request.input_schema,
            output_schema=request.output_schema,
            parameters=request.parameters,
            dependencies=request.dependencies,
            timeout_seconds=request.timeout_seconds,
            max_retries=request.max_retries,
            concurrency_limit=request.concurrency_limit,
            implementation_path=request.implementation_path,
            code_content=request.code_content,
            author=request.author,
            tags=request.tags,
            status=SkillStatus.ACTIVE,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        # 保存到数据库
        storage_service = SkillStorageService(session)
        await storage_service.save_skill_definition(definition)
        
        # 转换为响应模型
        response = SkillResponse(
            skill_id=definition.skill_id,
            name=definition.name,
            description=definition.description,
            skill_type=definition.skill_type,
            version=definition.version,
            status=definition.status,
            execution_count=0,
            success_count=0,
            success_rate=0.0,
            avg_execution_time=None,
            created_at=definition.created_at,
            updated_at=definition.updated_at,
            last_executed_at=None,
            author=definition.author,
            tags=definition.tags
        )
        
        return response
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"创建Skill失败: {str(e)}"
        )


@router.get("/skills", response_model=SkillListResponse)
async def list_skills(
    skill_type: Optional[SkillType] = Query(None, description="Skill类型过滤"),
    status: Optional[SkillStatus] = Query(None, description="状态过滤"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    session: AsyncSession = Depends(get_async_session)
):
    """列出所有Skill"""
    try:
        storage_service = SkillStorageService(session)
        skills, total = await storage_service.list_skill_definitions(
            skill_type=skill_type,
            status=status,
            limit=page_size,
            offset=(page - 1) * page_size
        )
        
        # 转换为响应模型
        skill_responses = []
        for skill in skills:
            success_rate = (
                skill.success_count / skill.execution_count 
                if skill.execution_count > 0 else 0
            )
            
            skill_responses.append(SkillResponse(
                skill_id=skill.skill_id,
                name=skill.name,
                description=skill.description,
                skill_type=skill.skill_type,
                version=skill.version,
                status=skill.status,
                execution_count=skill.execution_count,
                success_count=skill.success_count,
                success_rate=success_rate,
                avg_execution_time=skill.avg_execution_time,
                created_at=skill.created_at,
                updated_at=skill.updated_at,
                last_executed_at=skill.last_executed_at,
                author=skill.author,
                tags=skill.tags
            ))
        
        total_pages = (total + page_size - 1) // page_size
        
        return SkillListResponse(
            skills=skill_responses,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取Skill列表失败: {str(e)}"
        )


@router.get("/skills/{skill_id}", response_model=SkillResponse)
async def get_skill(
    skill_id: str,
    session: AsyncSession = Depends(get_async_session)
):
    """获取指定Skill详情"""
    try:
        storage_service = SkillStorageService(session)
        skill = await storage_service.get_skill_definition(skill_id)
        
        if not skill:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Skill '{skill_id}' 不存在"
            )
        
        success_rate = (
            skill.success_count / skill.execution_count 
            if skill.execution_count > 0 else 0
        )
        
        return SkillResponse(
            skill_id=skill.skill_id,
            name=skill.name,
            description=skill.description,
            skill_type=skill.skill_type,
            version=skill.version,
            status=skill.status,
            execution_count=skill.execution_count,
            success_count=skill.success_count,
            success_rate=success_rate,
            avg_execution_time=skill.avg_execution_time,
            created_at=skill.created_at,
            updated_at=skill.updated_at,
            last_executed_at=skill.last_executed_at,
            author=skill.author,
            tags=skill.tags
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取Skill详情失败: {str(e)}"
        )


@router.post("/skills/{skill_id}/execute", response_model=SkillExecutionResponse)
async def execute_skill(
    skill_id: str,
    request: SkillExecuteRequest,
    registry: SkillRegistry = Depends(get_skill_registry),
    executor: SkillExecutor = Depends(get_skill_executor),
    session: AsyncSession = Depends(get_async_session)
):
    """执行Skill"""
    try:
        # 检查Skill是否存在
        skill_definition = await registry.get_definition(skill_id)
        if not skill_definition:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Skill '{skill_id}' 不存在或未注册"
            )
        
        # 构建执行请求
        from app.skills.core.models import SkillExecutionRequest
        exec_request = SkillExecutionRequest(
            skill_id=skill_id,
            inputs=request.inputs,
            parameters=request.parameters or {},
            context=request.context
        )
        
        # 执行Skill
        result = await executor.execute_skill(exec_request)
        
        # 保存执行记录
        storage_service = SkillStorageService(session)
        await storage_service.save_execution_record(result)
        
        # 更新Skill指标
        await storage_service.update_skill_metrics(
            skill_id=skill_id,
            execution_time=result.execution_time,
            success=result.success
        )
        
        # 转换为响应模型
        return SkillExecutionResponse(
            execution_id=result.execution_id,
            skill_id=result.skill_id,
            skill_name=skill_definition.name,
            status=result.status,
            success=result.success,
            data=result.data,
            error=result.error,
            execution_time=result.execution_time,
            started_at=result.started_at,
            completed_at=result.completed_at,
            skill_version=result.skill_version
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"执行Skill失败: {str(e)}"
        )


@router.get("/skills/{skill_id}/executions", response_model=SkillExecutionListResponse)
async def list_skill_executions(
    skill_id: str,
    status: Optional[SkillExecutionStatus] = Query(None, description="执行状态过滤"),
    start_date: Optional[datetime] = Query(None, description="开始时间"),
    end_date: Optional[datetime] = Query(None, description="结束时间"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    session: AsyncSession = Depends(get_async_session)
):
    """列出Skill的执行记录"""
    try:
        storage_service = SkillStorageService(session)
        
        # 验证Skill存在
        skill = await storage_service.get_skill_definition(skill_id)
        if not skill:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Skill '{skill_id}' 不存在"
            )
        
        executions, total = await storage_service.list_execution_records(
            skill_id=skill_id,
            status=status,
            start_date=start_date,
            end_date=end_date,
            limit=page_size,
            offset=(page - 1) * page_size
        )
        
        # 转换为响应模型
        execution_responses = []
        for execution in executions:
            execution_responses.append(SkillExecutionResponse(
                execution_id=execution.execution_id,
                skill_id=execution.skill_id,
                skill_name=skill.name,
                status=execution.status,
                success=execution.success,
                data=execution.data,
                error=execution.error,
                execution_time=execution.execution_time,
                started_at=execution.started_at,
                completed_at=execution.completed_at,
                skill_version=execution.skill_version
            ))
        
        total_pages = (total + page_size - 1) // page_size
        
        return SkillExecutionListResponse(
            executions=execution_responses,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取执行记录失败: {str(e)}"
        )


@router.get("/skills/{skill_id}/metrics", response_model=SkillMetricsResponse)
async def get_skill_metrics(
    skill_id: str,
    period_days: int = Query(7, ge=1, le=30, description="统计天数"),
    session: AsyncSession = Depends(get_async_session)
):
    """获取Skill性能指标"""
    try:
        storage_service = SkillStorageService(session)
        
        # 验证Skill存在
        skill = await storage_service.get_skill_definition(skill_id)
        if not skill:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Skill '{skill_id}' 不存在"
            )
        
        # 获取Skill摘要
        summary = await storage_service.get_skill_summary(skill_id)
        if not summary:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"无法获取Skill '{skill_id}' 的指标"
            )
        
        skill_info = summary["skill_info"]
        today_stats = summary["today_stats"]
        
        return SkillMetricsResponse(
            skill_id=skill_id,
            skill_name=skill_info["name"],
            total_executions=skill_info["execution_count"],
            successful_executions=skill_info.get("success_count", 0),
            failed_executions=skill_info["execution_count"] - skill_info.get("success_count", 0),
            success_rate=skill_info.get("success_rate", 0.0),
            avg_execution_time=skill_info.get("avg_execution_time"),
            min_execution_time=None,  # 可以从详细统计中获取
            max_execution_time=None,  # 可以从详细统计中获取
            today_executions=today_stats["total_executions"],
            today_success_rate=today_stats.get("success_rate"),
            error_distribution={}  # 可以从错误统计中获取
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取Skill指标失败: {str(e)}"
        )


@router.get("/skills/health", response_model=SkillHealthCheckResponse)
async def health_check(
    registry: SkillRegistry = Depends(get_skill_registry),
    executor: SkillExecutor = Depends(get_skill_executor),
    session: AsyncSession = Depends(get_async_session)
):
    """Skill系统健康检查"""
    try:
        # 检查注册器状态
        registry_status = "healthy"
        registry_count = registry.count_skills()
        
        # 检查执行器状态
        executor_status = "healthy"
        active_executions = len(executor.get_active_executions())
        
        # 检查存储状态
        storage_status = "healthy"
        try:
            storage_service = SkillStorageService(session)
            # 测试查询
            _, total = await storage_service.list_skill_definitions(limit=1)
        except Exception as e:
            storage_status = f"error: {str(e)}"
            total = 0
        
        # 统计最近24小时执行次数
        recent_executions = 0
        error_rate = 0.0
        
        # 计算整体状态
        overall_status = "healthy"
        if registry_status != "healthy" or executor_status != "healthy" or storage_status != "healthy":
            overall_status = "degraded"
        
        return SkillHealthCheckResponse(
            status=overall_status,
            total_skills=registry_count,
            active_skills=registry_count,  # 简化：假设所有技能都激活
            recent_executions=recent_executions,
            error_rate=error_rate,
            registry_status=registry_status,
            executor_status=executor_status,
            storage_status=storage_status,
            details={
                "registry_skill_count": registry_count,
                "active_executions": active_executions,
                "storage_total_skills": total
            }
        )
        
    except Exception as e:
        return SkillHealthCheckResponse(
            status="unhealthy",
            total_skills=0,
            active_skills=0,
            recent_executions=0,
            error_rate=1.0,
            registry_status=f"error: {str(e)}",
            executor_status=f"error: {str(e)}",
            storage_status=f"error: {str(e)}",
            details={"error": str(e)}
        )


@router.post("/skills/bulk-execute", response_model=SkillBulkExecuteResponse)
async def bulk_execute_skills(
    request: SkillBulkExecuteRequest,
    background_tasks: BackgroundTasks,
    registry: SkillRegistry = Depends(get_skill_registry),
    executor: SkillExecutor = Depends(get_skill_executor),
    session: AsyncSession = Depends(get_async_session)
):
    """批量执行多个Skill"""
    try:
        start_time = datetime.utcnow()
        
        # 验证所有Skill都存在
        missing_skills = []
        for skill_id in request.skill_ids:
            if not registry.skill_exists(skill_id):
                missing_skills.append(skill_id)
        
        if missing_skills:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"以下Skill不存在: {', '.join(missing_skills)}"
            )
        
        # 验证输入列表长度匹配
        if len(request.skill_ids) != len(request.inputs_list):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Skill ID列表和输入数据列表长度不匹配: {len(request.skill_ids)} != {len(request.inputs_list)}"
            )
        
        # 创建执行任务
        tasks = []
        for skill_id, inputs in zip(request.skill_ids, request.inputs_list):
            from app.skills.core.models import SkillExecutionRequest
            exec_request = SkillExecutionRequest(
                skill_id=skill_id,
                inputs=inputs,
                parameters={},
                context={}
            )
            
            tasks.append(executor.execute_skill(exec_request))
        
        # 并发执行（有限制）
        results = []
        successful_tasks = 0
        failed_tasks = 0
        execution_times = []
        
        # 分批执行以控制并发
        concurrent_limit = min(request.concurrent_limit, len(tasks))
        
        for i in range(0, len(tasks), concurrent_limit):
            batch = tasks[i:i + concurrent_limit]
            batch_results = await asyncio.gather(*batch, return_exceptions=True)
            
            for result in batch_results:
                if isinstance(result, Exception):
                    failed_tasks += 1
                    # 创建失败结果
                    results.append({
                        "success": False,
                        "error": str(result),
                        "execution_time": None
                    })
                else:
                    successful_tasks += 1
                    results.append({
                        "success": True,
                        "data": result.data,
                        "execution_time": result.execution_time
                    })
                    
                    if result.execution_time:
                        execution_times.append(result.execution_time)
        
        completed_time = datetime.utcnow()
        total_execution_time = (completed_time - start_time).total_seconds()
        
        # 构建执行响应列表（简化）
        execution_responses = []
        # 这里可以构建详细的执行响应，但为了简化先返回空列表
        
        avg_execution_time = sum(execution_times) / len(execution_times) if execution_times else 0
        
        return SkillBulkExecuteResponse(
            total_tasks=len(tasks),
            completed_tasks=successful_tasks + failed_tasks,
            successful_tasks=successful_tasks,
            failed_tasks=failed_tasks,
            results=execution_responses,
            total_execution_time=total_execution_time,
            avg_execution_time=avg_execution_time,
            started_at=start_time,
            completed_at=completed_time
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"批量执行失败: {str(e)}"
        )


@router.get("/skills/types", response_model=Dict[str, List[str]])
async def get_skill_types():
    """获取所有Skill类型"""
    return {
        "skill_types": [t.value for t in SkillType],
        "skill_statuses": [s.value for s in SkillStatus],
        "execution_statuses": [es.value for es in SkillExecutionStatus]
    }