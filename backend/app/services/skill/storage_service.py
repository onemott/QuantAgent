"""
Skill存储服务
与现有SQLAlchemy和数据库服务集成
"""

import asyncio
import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta

from sqlalchemy import func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.services.database import get_db_session as get_async_session
from app.models.db_models import (
    SkillDefinitionDB, 
    SkillExecutionDB, 
    SkillMetricDB,
    SkillWorkflowDB
)
from app.skills.core.models import (
    SkillDefinition,
    SkillExecutionRequest,
    SkillExecutionResult,
    SkillMetrics,
    SkillType,
    SkillStatus,
    SkillExecutionStatus
)
from app.skills.core.exceptions import SkillError


class SkillStorageService:
    """Skill存储服务 - 负责Skill数据的持久化"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    # ========== Skill定义相关方法 ==========
    
    async def save_skill_definition(self, definition: SkillDefinition) -> str:
        """保存Skill定义到数据库"""
        
        # 检查是否已存在
        existing = await self.get_skill_definition_db(definition.skill_id)
        if existing:
            # 更新现有记录
            existing.name = definition.name
            existing.description = definition.description
            existing.skill_type = definition.skill_type.value
            existing.version = definition.version
            existing.input_schema = definition.input_schema
            existing.output_schema = definition.output_schema
            existing.parameters = definition.parameters
            existing.dependencies = definition.dependencies
            existing.timeout_seconds = definition.timeout_seconds
            existing.max_retries = definition.max_retries
            existing.concurrency_limit = definition.concurrency_limit
            existing.implementation_path = definition.implementation_path
            existing.code_content = definition.code_content
            existing.author = definition.author
            existing.tags = definition.tags
            existing.status = definition.status.value
            existing.updated_at = datetime.utcnow()
        else:
            # 创建新记录
            skill_db = SkillDefinitionDB(
                skill_id=definition.skill_id,
                name=definition.name,
                description=definition.description,
                skill_type=definition.skill_type.value,
                version=definition.version,
                input_schema=definition.input_schema,
                output_schema=definition.output_schema,
                parameters=definition.parameters,
                dependencies=definition.dependencies,
                timeout_seconds=definition.timeout_seconds,
                max_retries=definition.max_retries,
                concurrency_limit=definition.concurrency_limit,
                implementation_path=definition.implementation_path,
                code_content=definition.code_content,
                author=definition.author,
                tags=definition.tags,
                status=definition.status.value,
                created_at=definition.created_at or datetime.utcnow(),
                updated_at=definition.updated_at or datetime.utcnow()
            )
            self.session.add(skill_db)
        
        try:
            await self.session.commit()
            return definition.skill_id
        except Exception as e:
            await self.session.rollback()
            raise SkillError(f"保存Skill定义失败: {str(e)}")
    
    async def get_skill_definition_db(self, skill_id: str) -> Optional[SkillDefinitionDB]:
        """从数据库获取Skill定义"""
        stmt = select(SkillDefinitionDB).where(SkillDefinitionDB.skill_id == skill_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_skill_definition(self, skill_id: str) -> Optional[SkillDefinition]:
        """获取Skill定义（转换为模型）"""
        skill_db = await self.get_skill_definition_db(skill_id)
        if not skill_db:
            return None
        
        return SkillDefinition(
            skill_id=skill_db.skill_id,
            name=skill_db.name,
            description=skill_db.description,
            skill_type=SkillType(skill_db.skill_type),
            version=skill_db.version,
            input_schema=skill_db.input_schema,
            output_schema=skill_db.output_schema,
            parameters=skill_db.parameters,
            dependencies=skill_db.dependencies,
            timeout_seconds=skill_db.timeout_seconds,
            max_retries=skill_db.max_retries,
            concurrency_limit=skill_db.concurrency_limit,
            implementation_path=skill_db.implementation_path,
            code_content=skill_db.code_content,
            author=skill_db.author,
            tags=skill_db.tags,
            status=SkillStatus(skill_db.status),
            execution_count=skill_db.execution_count,
            success_count=skill_db.success_count,
            avg_execution_time=skill_db.avg_execution_time,
            created_at=skill_db.created_at,
            updated_at=skill_db.updated_at
        )
    
    async def list_skill_definitions(
        self, 
        skill_type: Optional[SkillType] = None,
        status: Optional[SkillStatus] = None,
        limit: int = 100,
        offset: int = 0
    ) -> Tuple[List[SkillDefinition], int]:
        """列出Skill定义"""
        
        # 构建查询条件
        conditions = []
        if skill_type:
            conditions.append(SkillDefinitionDB.skill_type == skill_type.value)
        if status:
            conditions.append(SkillDefinitionDB.status == status.value)
        
        # 查询总数
        count_stmt = select(func.count()).select_from(SkillDefinitionDB)
        if conditions:
            count_stmt = count_stmt.where(and_(*conditions))
        
        count_result = await self.session.execute(count_stmt)
        total = count_result.scalar()
        
        # 查询数据
        data_stmt = select(SkillDefinitionDB).order_by(SkillDefinitionDB.created_at.desc())
        if conditions:
            data_stmt = data_stmt.where(and_(*conditions))
        
        data_stmt = data_stmt.limit(limit).offset(offset)
        result = await self.session.execute(data_stmt)
        skill_dbs = result.scalars().all()
        
        # 转换为模型
        skills = []
        for skill_db in skill_dbs:
            skills.append(SkillDefinition(
                skill_id=skill_db.skill_id,
                name=skill_db.name,
                description=skill_db.description,
                skill_type=SkillType(skill_db.skill_type),
                version=skill_db.version,
                input_schema=skill_db.input_schema,
                output_schema=skill_db.output_schema,
                parameters=skill_db.parameters,
                dependencies=skill_db.dependencies,
                timeout_seconds=skill_db.timeout_seconds,
                max_retries=skill_db.max_retries,
                concurrency_limit=skill_db.concurrency_limit,
                implementation_path=skill_db.implementation_path,
                code_content=skill_db.code_content,
                author=skill_db.author,
                tags=skill_db.tags,
                status=SkillStatus(skill_db.status),
                execution_count=skill_db.execution_count,
                success_count=skill_db.success_count,
                avg_execution_time=skill_db.avg_execution_time,
                created_at=skill_db.created_at,
                updated_at=skill_db.updated_at
            ))
        
        return skills, total
    
    async def update_skill_metrics(
        self, 
        skill_id: str, 
        execution_time: Optional[float] = None,
        success: bool = True
    ) -> bool:
        """更新Skill执行指标"""
        
        skill_db = await self.get_skill_definition_db(skill_id)
        if not skill_db:
            return False
        
        # 更新执行计数
        skill_db.execution_count += 1
        if success:
            skill_db.success_count += 1
        
        # 更新平均执行时间
        if execution_time is not None:
            if skill_db.avg_execution_time is None:
                skill_db.avg_execution_time = execution_time
            else:
                # 加权平均
                current_avg = skill_db.avg_execution_time
                new_avg = (current_avg * (skill_db.success_count - 1) + execution_time) / skill_db.success_count
                skill_db.avg_execution_time = round(new_avg, 3)
        
        skill_db.last_executed_at = datetime.utcnow()
        skill_db.updated_at = datetime.utcnow()
        
        try:
            await self.session.commit()
            return True
        except Exception as e:
            await self.session.rollback()
            print(f"⚠️ 更新Skill指标失败 {skill_id}: {e}")
            return False
    
    # ========== Skill执行记录相关方法 ==========
    
    async def save_execution_record(self, result: SkillExecutionResult) -> str:
        """保存Skill执行记录"""
        
        inputs_hash = None
        if result.inputs_hash:
            inputs_hash = result.inputs_hash[:64]  # 确保不超过列长度
        
        execution_db = SkillExecutionDB(
            execution_id=result.execution_id,
            skill_id=result.skill_id,
            skill_version=result.skill_version,
            status=result.status.value,
            success=result.success,
            inputs=result.data.get("_original_inputs", {}) if result.data else {},
            inputs_hash=inputs_hash,
            parameters={},  # 从result中提取或单独存储
            context={},
            result_data=result.data,
            error_message=result.error,
            error_details=result.error_details,
            execution_time=result.execution_time,
            started_at=result.started_at,
            completed_at=result.completed_at,
            created_at=datetime.utcnow()
        )
        
        self.session.add(execution_db)
        
        try:
            await self.session.commit()
            return result.execution_id
        except Exception as e:
            await self.session.rollback()
            raise SkillError(f"保存执行记录失败: {str(e)}")
    
    async def get_execution_record(self, execution_id: str) -> Optional[SkillExecutionResult]:
        """获取Skill执行记录"""
        
        stmt = select(SkillExecutionDB).where(SkillExecutionDB.execution_id == execution_id)
        result = await self.session.execute(stmt)
        execution_db = result.scalar_one_or_none()
        
        if not execution_db:
            return None
        
        return SkillExecutionResult(
            execution_id=execution_db.execution_id,
            skill_id=execution_db.skill_id,
            status=SkillExecutionStatus(execution_db.status),
            success=execution_db.success,
            data=execution_db.result_data,
            error=execution_db.error_message,
            error_details=execution_db.error_details,
            execution_time=execution_db.execution_time,
            started_at=execution_db.started_at,
            completed_at=execution_db.completed_at,
            skill_version=execution_db.skill_version,
            inputs_hash=execution_db.inputs_hash
        )
    
    async def list_execution_records(
        self,
        skill_id: Optional[str] = None,
        status: Optional[SkillExecutionStatus] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0
    ) -> Tuple[List[SkillExecutionResult], int]:
        """列出Skill执行记录"""
        
        conditions = []
        if skill_id:
            conditions.append(SkillExecutionDB.skill_id == skill_id)
        if status:
            conditions.append(SkillExecutionDB.status == status.value)
        if start_date:
            conditions.append(SkillExecutionDB.created_at >= start_date)
        if end_date:
            conditions.append(SkillExecutionDB.created_at <= end_date)
        
        # 查询总数
        count_stmt = select(func.count()).select_from(SkillExecutionDB)
        if conditions:
            count_stmt = count_stmt.where(and_(*conditions))
        
        count_result = await self.session.execute(count_stmt)
        total = count_result.scalar()
        
        # 查询数据
        data_stmt = select(SkillExecutionDB).order_by(SkillExecutionDB.created_at.desc())
        if conditions:
            data_stmt = data_stmt.where(and_(*conditions))
        
        data_stmt = data_stmt.limit(limit).offset(offset)
        result = await self.session.execute(data_stmt)
        execution_dbs = result.scalars().all()
        
        # 转换为模型
        executions = []
        for execution_db in execution_dbs:
            executions.append(SkillExecutionResult(
                execution_id=execution_db.execution_id,
                skill_id=execution_db.skill_id,
                status=SkillExecutionStatus(execution_db.status),
                success=execution_db.success,
                data=execution_db.result_data,
                error=execution_db.error_message,
                error_details=execution_db.error_details,
                execution_time=execution_db.execution_time,
                started_at=execution_db.started_at,
                completed_at=execution_db.completed_at,
                skill_version=execution_db.skill_version,
                inputs_hash=execution_db.inputs_hash
            ))
        
        return executions, total
    
    # ========== Skill指标聚合方法 ==========
    
    async def aggregate_skill_metrics(
        self,
        skill_id: str,
        period_type: str = "daily",  # hourly, daily, weekly, monthly
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[SkillMetrics]:
        """聚合Skill性能指标"""
        
        if not start_date:
            start_date = datetime.utcnow() - timedelta(days=7)
        if not end_date:
            end_date = datetime.utcnow()
        
        # 这里可以实现复杂的聚合逻辑
        # 简化实现：查询执行记录并计算
        executions, _ = await self.list_execution_records(
            skill_id=skill_id,
            start_date=start_date,
            end_date=end_date
        )
        
        if not executions:
            return []
        
        # 按天分组
        executions_by_day = {}
        for execution in executions:
            if execution.completed_at:
                day_key = execution.completed_at.date().isoformat()
                if day_key not in executions_by_day:
                    executions_by_day[day_key] = []
                executions_by_day[day_key].append(execution)
        
        metrics_list = []
        for day_key, day_executions in executions_by_day.items():
            successful = [e for e in day_executions if e.success]
            failed = [e for e in day_executions if not e.success]
            
            execution_times = [
                e.execution_time for e in successful 
                if e.execution_time is not None
            ]
            
            period_start = datetime.strptime(day_key, "%Y-%m-%d").replace(tzinfo=None)
            period_end = period_start + timedelta(days=1)
            
            metrics = SkillMetrics(
                skill_id=skill_id,
                period_start=period_start,
                period_end=period_end,
                total_executions=len(day_executions),
                successful_executions=len(successful),
                failed_executions=len(failed),
                avg_execution_time=(
                    sum(execution_times) / len(execution_times) 
                    if execution_times else None
                ),
                min_execution_time=min(execution_times) if execution_times else None,
                max_execution_time=max(execution_times) if execution_times else None
            )
            
            metrics_list.append(metrics)
        
        return metrics_list
    
    async def get_skill_summary(self, skill_id: str) -> Dict[str, Any]:
        """获取Skill摘要信息"""
        
        skill_db = await self.get_skill_definition_db(skill_id)
        if not skill_db:
            return {}
        
        # 最近执行记录
        recent_executions, _ = await self.list_execution_records(
            skill_id=skill_id,
            limit=10
        )
        
        # 今日执行统计
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_executions, _ = await self.list_execution_records(
            skill_id=skill_id,
            start_date=today_start
        )
        
        today_successful = sum(1 for e in today_executions if e.success)
        today_failed = len(today_executions) - today_successful
        
        # 成功率统计
        total_success_rate = (
            skill_db.success_count / skill_db.execution_count 
            if skill_db.execution_count > 0 else 0
        )
        
        return {
            "skill_info": {
                "skill_id": skill_db.skill_id,
                "name": skill_db.name,
                "type": skill_db.skill_type,
                "version": skill_db.version,
                "status": skill_db.status,
                "execution_count": skill_db.execution_count,
                "success_rate": round(total_success_rate, 4),
                "avg_execution_time": skill_db.avg_execution_time,
                "last_executed": skill_db.last_executed_at.isoformat() if skill_db.last_executed_at else None
            },
            "today_stats": {
                "total_executions": len(today_executions),
                "successful": today_successful,
                "failed": today_failed,
                "success_rate": (
                    today_successful / len(today_executions) 
                    if today_executions else 0
                )
            },
            "recent_executions": [
                {
                    "execution_id": e.execution_id,
                    "status": e.status.value,
                    "success": e.success,
                    "execution_time": e.execution_time,
                    "completed_at": e.completed_at.isoformat() if e.completed_at else None
                }
                for e in recent_executions[:5]
            ]
        }