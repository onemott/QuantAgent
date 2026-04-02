"""
策略组合器工厂
根据配置创建不同类型的策略组合器
"""

import logging
from typing import Dict, Any, Type
from .base import StrategyComposer
from .weighted import WeightedComposer
from .voting import VotingComposer

logger = logging.getLogger(__name__)


class CompositionFactory:
    """策略组合器工厂"""
    
    # 注册可用的组合器类型
    COMPOSER_REGISTRY = {
        "weighted": WeightedComposer,
        "voting": VotingComposer,
    }
    
    @classmethod
    def create_composer(
        cls, 
        composition_type: str,
        composition_id: str,
        params: Dict[str, Any] = None
    ) -> StrategyComposer:
        """创建策略组合器
        Args:
            composition_type: 组合器类型 ('weighted', 'voting')
            composition_id: 组合器ID
            params: 组合器参数
        Returns:
            StrategyComposer实例
        Raises:
            ValueError: 如果组合器类型不支持
        """
        if composition_type not in cls.COMPOSER_REGISTRY:
            available = list(cls.COMPOSER_REGISTRY.keys())
            raise ValueError(
                f"不支持的组合器类型: {composition_type}. "
                f"可用类型: {available}"
            )
        
        composer_class = cls.COMPOSER_REGISTRY[composition_type]
        composer = composer_class(composition_id)
        
        if params:
            composer.set_parameters(params)
        
        logger.info(f"创建组合器: {composition_type}[{composition_id}] with params: {params}")
        return composer
    
    @classmethod
    def get_available_composers(cls) -> Dict[str, Dict[str, Any]]:
        """获取所有可用的组合器类型及其描述"""
        
        composers_info = {}
        for name, composer_class in cls.COMPOSER_REGISTRY.items():
            # 创建临时实例以获取参数空间
            temp_instance = composer_class(f"temp_{name}")
            param_space = temp_instance.get_param_space()
            
            composers_info[name] = {
                "name": composer_class.__name__,
                "description": composer_class.__doc__.strip().split('\n')[0] if composer_class.__doc__ else "",
                "param_space": param_space,
                "default_params": cls._get_default_params(name)
            }
        
        return composers_info
    
    @classmethod
    def _get_default_params(cls, composition_type: str) -> Dict[str, Any]:
        """获取组合器的默认参数"""
        
        defaults = {
            "weighted": {
                "threshold": 0.5,
                "weights": {}  # 空字典表示等权重
            },
            "voting": {
                "threshold": 0.5,
                "veto_power": False
            }
        }
        
        return defaults.get(composition_type, {})
    
    @classmethod
    def validate_composition_params(
        cls,
        composition_type: str,
        params: Dict[str, Any]
    ) -> tuple[bool, str]:
        """验证组合参数是否有效
        
        Returns:
            (is_valid, error_message)
        """
        
        if composition_type not in cls.COMPOSER_REGISTRY:
            return False, f"不支持的组合器类型: {composition_type}"
        
        # 获取组合器类
        composer_class = cls.COMPOSER_REGISTRY[composition_type]
        
        try:
            # 创建临时实例进行验证
            temp_instance = composer_class("validation_instance")
            
            # 检查必需参数
            required_params = getattr(composer_class, "REQUIRED_PARAMS", [])
            for param in required_params:
                if param not in params:
                    return False, f"缺少必需参数: {param}"
            
            # 尝试设置参数
            temp_instance.set_parameters(params)
            
            # 验证参数值范围
            param_space = temp_instance.get_param_space()
            for param_name, param_value in params.items():
                if param_name in param_space:
                    allowed_values = param_space[param_name]
                    if param_value not in allowed_values:
                        return False, f"参数 {param_name}={param_value} 不在允许范围内: {allowed_values}"
            
            return True, "参数验证通过"
            
        except Exception as e:
            return False, f"参数验证失败: {str(e)}"
    
    @classmethod
    def create_composer_from_config(cls, config: Dict[str, Any]) -> StrategyComposer:
        """从配置字典创建组合器
        
        Args:
            config: 配置字典，必须包含:
                - composition_type: 组合器类型
                - composition_id: 组合器ID
                - params: 参数字典 (可选)
        
        Returns:
            StrategyComposer实例
        """
        required_keys = ["composition_type", "composition_id"]
        for key in required_keys:
            if key not in config:
                raise ValueError(f"配置缺少必需键: {key}")
        
        composition_type = config["composition_type"]
        composition_id = config["composition_id"]
        params = config.get("params", {})
        
        return cls.create_composer(composition_type, composition_id, params)