"""
Skill执行器 - 负责Skill的执行、超时控制和并发管理
复用现有异步任务框架
"""

import asyncio
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional, AsyncGenerator
from datetime import datetime

from app.skills.core.models import (
    SkillDefinition,
    SkillExecutionRequest,
    SkillExecutionResult,
    SkillExecutionStatus,
    SkillMetrics
)
from app.skills.core.base import BaseSkill
from app.skills.core.exceptions import (
    SkillNotFoundError,
    SkillExecutionError,
    SkillTimeoutError,
    SkillInputValidationError
)


class SkillExecutor:
    """Skill执行器 - 管理Skill的完整执行生命周期"""
    
    def __init__(self, registry):
        self.registry = registry
        self._execution_counter = 0
        self._active_executions: Dict[str, asyncio.Task] = {}
        self._execution_metrics: Dict[str, SkillMetrics] = {}
        
    async def execute_skill(self, request: SkillExecutionRequest) -> SkillExecutionResult:
        """
        执行Skill的完整流程
        
        步骤：
        1. 验证请求
        2. 获取Skill实例
        3. 验证输入
        4. 执行Skill
        5. 记录结果和指标
        """
        execution_id = self._generate_execution_id()
        
        try:
            # 1. 验证请求
            self._validate_request(request)
            
            # 2. 获取Skill实例
            skill_instance = await self._get_skill_instance(request.skill_id)
            if not skill_instance:
                raise SkillNotFoundError(request.skill_id)
            
            # 3. 验证输入
            input_errors = skill_instance.validate_inputs(request.inputs)
            if input_errors:
                raise SkillInputValidationError(
                    skill_id=request.skill_id,
                    input_errors={"errors": input_errors}
                )
            
            # 4. 执行Skill（带超时控制）
            result_data = await self._execute_with_timeout(
                skill_instance, 
                request, 
                execution_id
            )
            
            # 5. 构建成功结果
            result = SkillExecutionResult(
                execution_id=execution_id,
                skill_id=request.skill_id,
                status=SkillExecutionStatus.COMPLETED,
                success=True,
                data=result_data,
                skill_version=skill_instance.skill_definition.version,
                inputs_hash=skill_instance._hash_inputs(request.inputs)
            )
            
        except Exception as e:
            # 处理执行失败
            result = self._create_failure_result(
                execution_id, 
                request.skill_id, 
                e,
                skill_instance.skill_definition.version if skill_instance else "unknown"
            )
        
        # 6. 更新执行指标
        await self._update_execution_metrics(result)
        
        return result
    
    async def _execute_with_timeout(
        self, 
        skill_instance: BaseSkill, 
        request: SkillExecutionRequest, 
        execution_id: str
    ) -> Dict[str, Any]:
        """带超时控制的Skill执行"""
        
        definition = skill_instance.skill_definition
        timeout = definition.timeout_seconds or 60
        
        try:
            # 使用asyncio.wait_for添加超时控制
            async with self._execution_context(execution_id, request.skill_id) as start_time:
                result_data = await asyncio.wait_for(
                    skill_instance.execute(request.inputs, request.context),
                    timeout=timeout
                )
                
                # 记录执行时间
                execution_time = time.time() - start_time
                
                return {
                    **result_data,
                    "_metadata": {
                        "execution_time": execution_time,
                        "execution_id": execution_id,
                        "skill_version": definition.version
                    }
                }
                
        except asyncio.TimeoutError:
            raise SkillTimeoutError(
                skill_id=request.skill_id,
                timeout_seconds=timeout,
                execution_id=execution_id
            )
        except Exception as e:
            # 包装原始异常
            raise SkillExecutionError(
                skill_id=request.skill_id,
                error=str(e),
                execution_id=execution_id,
                original_exception=str(type(e).__name__)
            )
    
    @asynccontextmanager
    async def _execution_context(self, execution_id: str, skill_id: str) -> AsyncGenerator[float, None]:
        """执行上下文管理器"""
        start_time = time.time()
        
        # 记录活跃执行
        self._active_executions[execution_id] = asyncio.current_task()
        
        try:
            yield start_time
        finally:
            # 清理活跃执行
            if execution_id in self._active_executions:
                del self._active_executions[execution_id]
    
    async def _get_skill_instance(self, skill_id: str) -> Optional[BaseSkill]:
        """获取Skill实例（带异常处理）"""
        try:
            return await self.registry.get_instance(skill_id)
        except Exception as e:
            print(f"⚠️ 获取Skill实例失败 {skill_id}: {e}")
            return None
    
    def _validate_request(self, request: SkillExecutionRequest) -> None:
        """验证执行请求"""
        if not request.skill_id:
            raise ValueError("skill_id不能为空")
        
        if not self.registry.skill_exists(request.skill_id):
            raise SkillNotFoundError(request.skill_id)
    
    def _generate_execution_id(self) -> str:
        """生成执行ID"""
        self._execution_counter += 1
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        return f"exec_{timestamp}_{self._execution_counter:06d}"
    
    def _create_failure_result(
        self, 
        execution_id: str, 
        skill_id: str, 
        error: Exception,
        skill_version: str
    ) -> SkillExecutionResult:
        """创建失败结果"""
        
        error_message = str(error)
        error_details = {}
        
        # 提取异常详情
        if hasattr(error, 'details'):
            error_details = error.details
        
        return SkillExecutionResult(
            execution_id=execution_id,
            skill_id=skill_id,
            status=SkillExecutionStatus.FAILED,
            success=False,
            error=error_message,
            error_details=error_details,
            skill_version=skill_version
        )
    
    async def _update_execution_metrics(self, result: SkillExecutionResult) -> None:
        """更新执行指标"""
        skill_id = result.skill_id
        today = datetime.utcnow().date().isoformat()
        
        if skill_id not in self._execution_metrics:
            self._execution_metrics[skill_id] = SkillMetrics(
                skill_id=skill_id,
                period_start=datetime.utcnow(),
                period_end=datetime.utcnow(),
                total_executions=0,
                successful_executions=0,
                failed_executions=0
            )
        
        metrics = self._execution_metrics[skill_id]
        metrics.total_executions += 1
        
        if result.success:
            metrics.successful_executions += 1
            # 更新执行时间统计
            if result.execution_time:
                if metrics.avg_execution_time is None:
                    metrics.avg_execution_time = result.execution_time
                    metrics.min_execution_time = result.execution_time
                    metrics.max_execution_time = result.execution_time
                else:
                    # 更新平均值
                    total_time = metrics.avg_execution_time * (metrics.successful_executions - 1)
                    metrics.avg_execution_time = (total_time + result.execution_time) / metrics.successful_executions
                    
                    # 更新最小/最大值
                    metrics.min_execution_time = min(metrics.min_execution_time or float('inf'), result.execution_time)
                    metrics.max_execution_time = max(metrics.max_execution_time or 0, result.execution_time)
        else:
            metrics.failed_executions += 1
        
        # 更新成功率
        metrics.success_rate = (
            metrics.successful_executions / metrics.total_executions 
            if metrics.total_executions > 0 else 0
        )
    
    def get_active_executions(self) -> Dict[str, str]:
        """获取活跃执行列表"""
        return {
            exec_id: str(task) 
            for exec_id, task in self._active_executions.items()
        }
    
    def get_execution_metrics(self, skill_id: Optional[str] = None) -> Dict[str, Any]:
        """获取执行指标"""
        if skill_id:
            if skill_id in self._execution_metrics:
                return self._execution_metrics[skill_id].dict()
            return {}
        
        return {skill_id: metrics.dict() for skill_id, metrics in self._execution_metrics.items()}
    
    async def cancel_execution(self, execution_id: str) -> bool:
        """取消正在执行的任务"""
        if execution_id in self._active_executions:
            task = self._active_executions[execution_id]
            task.cancel()
            
            try:
                await task
            except asyncio.CancelledError:
                pass
            
            return True
        return False