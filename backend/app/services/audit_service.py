"""
Audit Logging Service
Records critical system actions and user interventions.
"""

import logging
from typing import Dict, Any, Optional
from app.services.database import get_db
from app.models.db_models import AuditLog

logger = logging.getLogger(__name__)

class AuditService:
    async def log_event(
        self,
        action: str,
        user_id: str = "system",
        resource: str = None,
        details: Dict[str, Any] = None,
        ip_address: str = None
    ):
        """
        Record an audit log entry.
        
        Args:
            action: The action performed (e.g., "ORDER_CREATE", "CONFIG_UPDATE")
            user_id: ID of the user or "system"
            resource: Target resource (e.g., "BTCUSDT", "settings")
            details: JSON details
            ip_address: Origin IP
        """
        if details is None:
            details = {}
            
        try:
            async with get_db() as session:
                log_entry = AuditLog(
                    action=action,
                    user_id=user_id,
                    resource=resource,
                    details=details,
                    ip_address=ip_address
                )
                session.add(log_entry)
                # Commit is handled by context manager
            logger.info(f"Audit Log: {action} by {user_id} on {resource}")
        except Exception as e:
            logger.error(f"Failed to write audit log: {e}")

# Singleton
audit_service = AuditService()
