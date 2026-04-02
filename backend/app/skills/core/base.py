"""
智能体Skill抽象基类和注册器
复用现有异步架构和依赖注入模式
"""

import asyncio
import hashlib
import inspect
import json
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type, TypeVar
from datetime import datetime
import uuid

from app.skills.core.models import (
    SkillDefinition, 
    SkillExecutionRequest, 
    SkillExecutionResult,
    SkillExecutionStatus,
    SkillType
)
from app.skills.core.exceptions import (
    SkillError,
    SkillInputValidationError,
    SkillExecutionError
)

T = TypeVar('T', bound='BaseSkill')

class BaseSkill(ABC):
    """Skill抽象基类 - 所有Skill必须继承此类"""
    
    def __init__(self, skill_definition: SkillDefinition):
        self.skill_definition = skill_definition
        self.skill_id = skill_definition.skill_id
        self.skill_type = skill_definition.skill_type
        self._initialized = False
        
    async def initialize(self) -> None:
        """初始化Skill（可选）"""
        if not self._initialized:
            await self._validate_dependencies()
            self._initialized = True
    
    async def _validate_dependencies(self) -> None:
        """验证Skill依赖"""
        if hasattr(self, 'required_dependencies'):
            missing = []
            for dep in self.required_dependencies:
                if not await self._check_dependency(dep):
                    missing.append(dep)
            
            if missing:
                from app.skills.core.exceptions import SkillDependencyError
                raise SkillDependencyError(
                    skill_id=self.skill_id,
                    missing_dependencies=missing
                )
    
    async def _check_dependency(self, dependency: str) -> bool:
        """检查依赖是否存在（可被子类重写）"""
        # 基础实现，子类可以实现更复杂的依赖检查
        try:
            __import__(dependency)
            return True
        except ImportError:
            return False
    
    @abstractmethod
    async def execute(self, inputs: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        执行Skill的核心逻辑
        
        Args:
            inputs: 输入数据，必须符合input_schema定义
            context: 执行上下文（可选）
            
        Returns:
            执行结果，必须符合output_schema定义
        """
        pass
    
    def validate_inputs(self, inputs: Dict[str, Any]) -> List[str]:
        """
        验证输入数据（基础实现，子类可扩展）
        
        Args:
            inputs: 输入数据
            
        Returns:
            错误信息列表，空列表表示验证通过
        """
        errors = []
        
        # 检查必填字段
        input_schema = self.skill_definition.input_schema
        if isinstance(input_schema, dict) and "required" in input_schema:
            required_fields = input_schema.get("required", [])
            for field in required_fields:
                if field not in inputs:
                    errors.append(f"缺少必填字段: {field}")
        
        return errors
    
    def get_execution_context(self, execution_id: str, request: SkillExecutionRequest) -> Dict[str, Any]:
        """获取执行上下文"""
        context = {
            "execution_id": execution_id,
            "skill_id": self.skill_id,
            "skill_version": self.skill_definition.version,
            "request_timestamp": datetime.utcnow().isoformat(),
            "request_hash": self._hash_inputs(request.inputs)
        }
        
        if request.context:
            context.update(request.context)
        
        return context
    
    def _hash_inputs(self, inputs: Dict[str, Any]) -> str:
        """计算输入数据的哈希值"""
        inputs_str = json.dumps(inputs, sort_keys=True)
        return hashlib.md5(inputs_str.encode()).hexdigest()
    
    def __str__(self) -> str:
        return f"Skill({self.skill_id}, type={self.skill_type}, version={self.skill_definition.version})"
    
    def __repr__(self) -> str:
        return self.__str__()


class SkillRegistry:
    """Skill注册管理器 - 负责Skill的注册、查找和管理"""
    
    def __init__(self):
        self._skills: Dict[str, SkillDefinition] = {}
        self._skill_classes: Dict[str, Type[BaseSkill]] = {}
        self._skill_instances: Dict[str, BaseSkill] = {}
    
    def register(self, skill_class: Type[BaseSkill], definition: SkillDefinition) -> None:
        """注册Skill类和定义"""
        skill_id = definition.skill_id
        
        if skill_id in self._skill_classes:
            from app.skills.core.exceptions import SkillAlreadyExistsError
            raise SkillAlreadyExistsError(skill_id)
        
        # 验证定义
        self._validate_definition(definition)
        
        # 注册
        self._skill_classes[skill_id] = skill_class
        self._skills[skill_id] = definition
        
        print(f"[REG] Skill注册成功: {skill_id} ({definition.skill_type})")
    
    def unregister(self, skill_id: str) -> bool:
        """取消注册Skill"""
        if skill_id in self._skill_classes:
            del self._skill_classes[skill_id]
            del self._skills[skill_id]
            
            if skill_id in self._skill_instances:
                del self._skill_instances[skill_id]
            
            print(f"[UNREG] Skill取消注册: {skill_id}")
            return True
        return False
    
    def get_definition(self, skill_id: str) -> Optional[SkillDefinition]:
        """获取Skill定义"""
        return self._skills.get(skill_id)
    
    def get_skill_class(self, skill_id: str) -> Optional[Type[BaseSkill]]:
        """获取Skill类"""
        return self._skill_classes.get(skill_id)
    
    async def get_instance(self, skill_id: str) -> Optional[BaseSkill]:
        """获取Skill实例（懒加载）"""
        if skill_id not in self._skill_instances:
            skill_class = self.get_skill_class(skill_id)
            if not skill_class:
                return None
            
            definition = self.get_definition(skill_id)
            if not definition:
                return None
            
            # 创建实例并初始化
            instance = skill_class(definition)
            try:
                await instance.initialize()
                self._skill_instances[skill_id] = instance
            except Exception as e:
                print(f"[WARN] Skill实例化失败 {skill_id}: {e}")
                return None
        
        return self._skill_instances.get(skill_id)
    
    def list_skills(self, skill_type: Optional[SkillType] = None) -> List[SkillDefinition]:
        """列出所有Skill（可过滤类型）"""
        if skill_type:
            return [
                definition for definition in self._skills.values()
                if definition.skill_type == skill_type
            ]
        return list(self._skills.values())
    
    def skill_exists(self, skill_id: str) -> bool:
        """检查Skill是否存在"""
        return skill_id in self._skill_classes
    
    def count_skills(self, skill_type: Optional[SkillType] = None) -> int:
        """统计Skill数量"""
        if skill_type:
            return len([
                s for s in self._skills.values() 
                if s.skill_type == skill_type
            ])
        return len(self._skills)
    
    def _validate_definition(self, definition: SkillDefinition) -> List[str]:
        """验证Skill定义（基础验证）"""
        errors = []
        
        # 检查必填字段
        if not definition.skill_id:
            errors.append("skill_id不能为空")
        
        if not definition.name:
            errors.append("name不能为空")
        
        if not definition.skill_type:
            errors.append("skill_type不能为空")
        
        if not definition.version:
            errors.append("version不能为空")
        
        # 检查版本格式
        import re
        if not re.match(r"^\d+\.\d+\.\d+$", definition.version):
            errors.append("version格式必须为x.y.z")
        
        if errors:
            from app.skills.core.exceptions import SkillValidationError
            raise SkillValidationError(
                skill_id=definition.skill_id,
                validation_errors={"errors": errors}
            )
        
        return errors
    
    def clear(self) -> None:
        """清空所有注册的Skill"""
        self._skills.clear()
        self._skill_classes.clear()
        self._skill_instances.clear()
        print("[CLEAR] Skill注册器已清空")