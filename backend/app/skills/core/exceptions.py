"""
智能体Skill异常定义
与现有异常处理体系保持一致
"""

from typing import Optional, Any

class SkillError(Exception):
    """Skill基类异常"""
    def __init__(self, message: str, skill_id: Optional[str] = None, **kwargs):
        self.message = message
        self.skill_id = skill_id
        self.details = kwargs
        super().__init__(message)

class SkillNotFoundError(SkillError):
    """Skill不存在异常"""
    def __init__(self, skill_id: str, **kwargs):
        super().__init__(
            f"Skill '{skill_id}' 不存在",
            skill_id=skill_id,
            **kwargs
        )

class SkillValidationError(SkillError):
    """Skill验证失败异常"""
    def __init__(self, skill_id: str, validation_errors: dict, **kwargs):
        super().__init__(
            f"Skill '{skill_id}' 验证失败: {validation_errors}",
            skill_id=skill_id,
            validation_errors=validation_errors,
            **kwargs
        )

class SkillExecutionError(SkillError):
    """Skill执行失败异常"""
    def __init__(self, skill_id: str, error: str, execution_id: Optional[str] = None, **kwargs):
        super().__init__(
            f"Skill '{skill_id}' 执行失败: {error}",
            skill_id=skill_id,
            error=error,
            execution_id=execution_id,
            **kwargs
        )

class SkillTimeoutError(SkillExecutionError):
    """Skill执行超时异常"""
    def __init__(self, skill_id: str, timeout_seconds: int, execution_id: Optional[str] = None):
        super().__init__(
            skill_id=skill_id,
            error=f"执行超时 ({timeout_seconds}秒)",
            execution_id=execution_id,
            timeout_seconds=timeout_seconds
        )

class SkillInputValidationError(SkillError):
    """Skill输入数据验证失败异常"""
    def __init__(self, skill_id: str, input_errors: dict, **kwargs):
        super().__init__(
            f"Skill '{skill_id}' 输入数据验证失败: {input_errors}",
            skill_id=skill_id,
            input_errors=input_errors,
            **kwargs
        )

class SkillDependencyError(SkillError):
    """Skill依赖缺失异常"""
    def __init__(self, skill_id: str, missing_dependencies: list, **kwargs):
        super().__init__(
            f"Skill '{skill_id}' 缺少依赖: {missing_dependencies}",
            skill_id=skill_id,
            missing_dependencies=missing_dependencies,
            **kwargs
        )

class SkillRegistryError(SkillError):
    """Skill注册失败异常"""
    def __init__(self, skill_id: str, reason: str, **kwargs):
        super().__init__(
            f"Skill '{skill_id}' 注册失败: {reason}",
            skill_id=skill_id,
            reason=reason,
            **kwargs
        )

class SkillAlreadyExistsError(SkillRegistryError):
    """Skill已存在异常"""
    def __init__(self, skill_id: str, **kwargs):
        super().__init__(
            skill_id=skill_id,
            reason=f"Skill '{skill_id}' 已存在"
        )

class SkillExecutionLimitExceeded(SkillError):
    """Skill执行限制超过异常"""
    def __init__(self, skill_id: str, limit_type: str, limit_value: Any, current_value: Any):
        super().__init__(
            f"Skill '{skill_id}' {limit_type}限制超过: {current_value}/{limit_value}",
            skill_id=skill_id,
            limit_type=limit_type,
            limit_value=limit_value,
            current_value=current_value
        )

class SkillConfigurationError(SkillError):
    """Skill配置错误异常"""
    def __init__(self, skill_id: str, config_errors: dict, **kwargs):
        super().__init__(
            f"Skill '{skill_id}' 配置错误: {config_errors}",
            skill_id=skill_id,
            config_errors=config_errors,
            **kwargs
        )