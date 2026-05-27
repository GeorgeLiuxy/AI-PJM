"""Secret store API schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SecretCreateRequest(BaseModel):
    """Create an encrypted project secret."""

    project_id: int
    name: str = Field(..., min_length=1, max_length=100)
    provider: str = Field(..., min_length=1, max_length=100)
    value: str = Field(..., min_length=1, max_length=20000)
    description: Optional[str] = Field(default=None, max_length=500)


class SecretRotateRequest(BaseModel):
    """Rotate an existing secret value."""

    value: str = Field(..., min_length=1, max_length=20000)
    description: Optional[str] = Field(default=None, max_length=500)


class SecretRecordResponse(BaseModel):
    """Secret metadata response. Plaintext is never returned."""

    id: int
    project_id: int
    name: str
    provider: str
    description: Optional[str] = None
    key_id: str
    value_mask: str
    status: str
    created_by_user_id: Optional[int] = None
    updated_by_user_id: Optional[int] = None
    last_used_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
