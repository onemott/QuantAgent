from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any
from app.services.risk_manager import risk_manager
from app.models.db_models import AuditLog
from app.services.database import get_db
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/config")
async def get_risk_config():
    """获取当前风控配置"""
    return await risk_manager.get_config()

@router.post("/config")
async def update_risk_config(new_config: Dict[str, float]):
    """更新风控配置并记录审计日志"""
    # 验证字段
    allowed_keys = {
        "MAX_SINGLE_POSITION_PCT", 
        "MAX_TOTAL_DRAWDOWN_PCT", 
        "MAX_DAILY_LOSS_PCT", 
        "PRICE_DEVIATION_PCT"
    }
    for key in new_config:
        if key not in allowed_keys:
            raise HTTPException(status_code=400, detail=f"Invalid config key: {key}")
        if not isinstance(new_config[key], (int, float)) or new_config[key] < 0:
            raise HTTPException(status_code=400, detail=f"Invalid value for {key}")

    old_config = await risk_manager.get_config()
    await risk_manager.update_config(new_config)

    # 记录审计日志
    try:
        async with get_db() as session:
            audit = AuditLog(
                action="RISK_CONFIG_UPDATE",
                user_id="system",
                resource="risk_manager",
                details={
                    "old": old_config,
                    "new": new_config
                }
            )
            session.add(audit)
            await session.commit()
    except Exception as e:
        logger.warning(f"Failed to log risk config update: {e}")

    return {"message": "Risk configuration updated successfully", "config": new_config}

@router.post("/kill-switch/trigger")
async def trigger_kill_switch():
    """手动触发全局熔断"""
    await risk_manager.trigger_kill_switch()
    return {"message": "Global Kill Switch Activated"}

@router.post("/kill-switch/reset")
async def reset_kill_switch():
    """重置全局熔断"""
    await risk_manager.reset_kill_switch()
    return {"message": "Global Kill Switch Reset"}
