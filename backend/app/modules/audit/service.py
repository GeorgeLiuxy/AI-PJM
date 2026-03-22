"""Action log service for recording actions"""

from typing import Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import ActionLog
from app.common.enums import ActionType, OperatorType, BizType


class ActionLogService:
    """Action log service - 记录所有关键动作"""
    
    async def log(
        self,
        db: AsyncSession,
        biz_type: BizType | str,
        biz_id: int,
        action_type: ActionType | str,
        operator_type: OperatorType | str,
        operator_ref: Optional[str] = None,
        from_status: Optional[str] = None,
        to_status: Optional[str] = None,
        action_payload: Optional[dict[str, Any]] = None,
        comment: Optional[str] = None,
    ) -> ActionLog:
        """
        记录动作日志
        
        Args:
            db: 数据库会话
            biz_type: 业务类型 (item | analysis | output)
            biz_id: 业务对象 ID
            action_type: 动作类型
            operator_type: 操作者类型 (user | ai | system)
            operator_ref: 操作者标识
            from_status: 变更前状态
            to_status: 变更后状态
            action_payload: 动作负载数据
            comment: 备注
        
        Returns:
            创建的 ActionLog 对象
        """
        action_log = ActionLog(
            biz_type=biz_type.value if isinstance(biz_type, BizType) else biz_type,
            biz_id=biz_id,
            action_type=action_type.value if isinstance(action_type, ActionType) else action_type,
            operator_type=operator_type.value if isinstance(operator_type, OperatorType) else operator_type,
            operator_ref=operator_ref,
            from_status=from_status,
            to_status=to_status,
            action_payload=action_payload,
            comment=comment,
        )
        
        db.add(action_log)
        await db.flush()
        
        return action_log


# Global service instance
action_log_service = ActionLogService()
