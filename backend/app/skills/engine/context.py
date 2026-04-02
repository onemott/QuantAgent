"""
Skill执行上下文管理器
提供技能执行时的上下文信息和数据访问
"""

import asyncio
import json
from typing import Any, Dict, Optional, List
from datetime import datetime
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum

from app.skills.core.models import SkillExecutionRequest


class ContextType(str, Enum):
    """上下文数据类型"""
    MARKET_DATA = "market_data"
    STRATEGY_CONFIG = "strategy_config"
    RISK_PROFILE = "risk_profile"
    USER_PREFERENCE = "user_preference"
    SYSTEM_STATE = "system_state"
    EXECUTION_HISTORY = "execution_history"


@dataclass
class ContextData:
    """上下文数据条目"""
    data_type: ContextType
    data: Any
    source: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    ttl_seconds: Optional[int] = None  # 过期时间（秒）
    
    def is_expired(self) -> bool:
        """检查数据是否过期"""
        if self.ttl_seconds is None:
            return False
        
        age = (datetime.utcnow() - self.timestamp).total_seconds()
        return age > self.ttl_seconds


class SkillContextManager:
    """
    Skill上下文管理器
    管理Skill执行时的上下文信息，支持数据共享和状态管理
    """
    
    def __init__(self):
        self._context_storage: Dict[str, ContextData] = {}
        self._execution_contexts: Dict[str, Dict[str, Any]] = {}
        self._context_lock = asyncio.Lock()
        
    async def create_execution_context(
        self, 
        request: SkillExecutionRequest,
        execution_id: str
    ) -> Dict[str, Any]:
        """
        创建执行上下文
        
        Args:
            request: Skill执行请求
            execution_id: 执行ID
            
        Returns:
            执行上下文字典
        """
        context = {
            "execution_id": execution_id,
            "skill_id": request.skill_id,
            "created_at": datetime.utcnow().isoformat(),
            "inputs": request.inputs.copy() if request.inputs else {},
            "parameters": request.parameters.copy() if request.parameters else {},
            "user_context": request.context.copy() if request.context else {},
            "system_context": await self._get_system_context(),
            "shared_data": {}
        }
        
        self._execution_contexts[execution_id] = context
        return context
    
    async def get_execution_context(self, execution_id: str) -> Optional[Dict[str, Any]]:
        """获取执行上下文"""
        return self._execution_contexts.get(execution_id)
    
    async def update_execution_context(
        self, 
        execution_id: str, 
        updates: Dict[str, Any]
    ) -> bool:
        """更新执行上下文"""
        if execution_id not in self._execution_contexts:
            return False
        
        async with self._context_lock:
            context = self._execution_contexts[execution_id]
            context.update(updates)
        
        return True
    
    async def share_data_in_context(
        self,
        execution_id: str,
        key: str,
        value: Any,
        data_type: Optional[ContextType] = None
    ) -> bool:
        """在上下文中共享数据"""
        if execution_id not in self._execution_contexts:
            return False
        
        async with self._context_lock:
            context = self._execution_contexts[execution_id]
            
            if "shared_data" not in context:
                context["shared_data"] = {}
            
            shared_data = context["shared_data"]
            shared_data[key] = {
                "value": value,
                "type": data_type.value if data_type else "custom",
                "shared_at": datetime.utcnow().isoformat()
            }
        
        return True
    
    async def get_shared_data(
        self,
        execution_id: str,
        key: str
    ) -> Optional[Any]:
        """获取共享数据"""
        context = await self.get_execution_context(execution_id)
        if not context or "shared_data" not in context:
            return None
        
        shared_data = context["shared_data"]
        if key not in shared_data:
            return None
        
        return shared_data[key]["value"]
    
    async def store_global_context(
        self,
        key: str,
        data: Any,
        data_type: ContextType,
        source: str,
        ttl_seconds: Optional[int] = None
    ) -> None:
        """存储全局上下文数据"""
        async with self._context_lock:
            context_data = ContextData(
                data_type=data_type,
                data=data,
                source=source,
                ttl_seconds=ttl_seconds
            )
            self._context_storage[key] = context_data
    
    async def retrieve_global_context(
        self,
        key: str
    ) -> Optional[Any]:
        """检索全局上下文数据"""
        async with self._context_lock:
            if key not in self._context_storage:
                return None
            
            context_data = self._context_storage[key]
            
            # 检查是否过期
            if context_data.is_expired():
                del self._context_storage[key]
                return None
            
            return context_data.data
    
    async def search_global_context(
        self,
        data_type: Optional[ContextType] = None,
        source: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """搜索全局上下文数据"""
        results = []
        
        async with self._context_lock:
            for key, context_data in self._context_storage.items():
                # 检查是否过期
                if context_data.is_expired():
                    continue
                
                # 过滤条件
                if data_type and context_data.data_type != data_type:
                    continue
                
                if source and context_data.source != source:
                    continue
                
                results.append({
                    "key": key,
                    "data": context_data.data,
                    "type": context_data.data_type.value,
                    "source": context_data.source,
                    "timestamp": context_data.timestamp.isoformat()
                })
        
        # 按时间戳排序（最新的在前）
        results.sort(key=lambda x: x["timestamp"], reverse=True)
        return results
    
    async def clear_expired_context(self) -> int:
        """清理过期的上下文数据，返回清理数量"""
        expired_keys = []
        
        async with self._context_lock:
            for key, context_data in self._context_storage.items():
                if context_data.is_expired():
                    expired_keys.append(key)
            
            for key in expired_keys:
                del self._context_storage[key]
        
        # 清理过期的执行上下文（超过24小时）
        cutoff_time = datetime.utcnow().timestamp() - 86400  # 24小时
        expired_executions = []
        
        for exec_id, context in self._execution_contexts.items():
            created_at = context.get("created_at")
            if created_at:
                try:
                    created_time = datetime.fromisoformat(created_at.replace('Z', '+00:00')).timestamp()
                    if created_time < cutoff_time:
                        expired_executions.append(exec_id)
                except (ValueError, KeyError):
                    pass
        
        for exec_id in expired_executions:
            del self._execution_contexts[exec_id]
        
        return len(expired_keys) + len(expired_executions)
    
    async def _get_system_context(self) -> Dict[str, Any]:
        """获取系统上下文信息"""
        # 这里可以集成现有的系统状态服务
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "system_uptime": await self._get_system_uptime(),
            "available_services": await self._get_available_services(),
            "resource_usage": await self._get_resource_usage()
        }
    
    async def _get_system_uptime(self) -> float:
        """获取系统运行时间（简化实现）"""
        # 实际项目中可以从系统监控服务获取
        return 3600.0  # 1小时
    
    async def _get_available_services(self) -> List[str]:
        """获取可用服务列表"""
        # 实际项目中可以从服务发现获取
        return ["market_data", "backtest_engine", "risk_manager", "database"]
    
    async def _get_resource_usage(self) -> Dict[str, Any]:
        """获取资源使用情况"""
        # 实际项目中可以从监控系统获取
        return {
            "cpu_percent": 45.2,
            "memory_percent": 67.8,
            "disk_usage_percent": 32.1
        }
    
    @asynccontextmanager
    async def context_session(self, execution_id: str):
        """
        上下文会话管理器
        用于管理执行上下文的生命周期
        """
        try:
            yield
        finally:
            # 会话结束时，可以执行清理操作
            pass
    
    def get_context_stats(self) -> Dict[str, Any]:
        """获取上下文管理器统计信息"""
        return {
            "global_context_count": len(self._context_storage),
            "active_executions": len(self._execution_contexts),
            "context_types": {
                data_type.value: sum(
                    1 for ctx in self._context_storage.values() 
                    if ctx.data_type == data_type
                )
                for data_type in ContextType
            }
        }