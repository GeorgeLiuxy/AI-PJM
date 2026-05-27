"""Audit API schemas."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class AuditEventResponse(BaseModel):
    """Audit event response."""

    id: int
    project_id: Optional[int] = None
    actor_user_id: Optional[int] = None
    actor_ref: str
    action: str
    entity_type: str
    entity_id: Optional[int] = None
    summary: str
    metadata_json: Optional[dict[str, Any]] = None
    created_at: datetime

    class Config:
        from_attributes = True

