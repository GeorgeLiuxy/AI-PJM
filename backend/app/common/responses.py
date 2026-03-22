"""Common response models for API endpoints"""

from typing import Any, Generic, Optional, TypeVar
from pydantic import BaseModel, Field
from datetime import datetime


T = TypeVar("T")


class SuccessResponse(BaseModel, Generic[T]):
    """Standard success response wrapper"""
    code: int = Field(default=200, description="Status code")
    message: str = Field(default="success", description="Response message")
    data: Optional[T] = Field(default=None, description="Response data")


class ErrorResponse(BaseModel):
    """Standard error response"""
    code: int = Field(description="Error code")
    message: str = Field(description="Error message")
    details: Optional[dict[str, Any]] = Field(default=None, description="Error details")


class HealthResponse(BaseModel):
    """Health check response"""
    status: str = Field(description="Service status")
    version: str = Field(description="Application version")
    timestamp: datetime = Field(description="Current timestamp")
    database: Optional[bool] = Field(default=None, description="Database connection status")


class PaginationMeta(BaseModel):
    """Pagination metadata"""
    total: int = Field(description="Total number of items")
    page: int = Field(description="Current page number")
    page_size: int = Field(description="Number of items per page")
    total_pages: int = Field(description="Total number of pages")


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated response wrapper"""
    code: int = Field(default=200, description="Status code")
    message: str = Field(default="success", description="Response message")
    data: list[T] = Field(description="List of items")
    meta: PaginationMeta = Field(description="Pagination information")


def success_response(
    data: Any = None,
    message: str = "success",
    code: int = 200
) -> dict[str, Any]:
    """
    Create a standardized success response.

    Args:
        data: Response data
        message: Response message
        code: Status code

    Returns:
        Dictionary with success response format
    """
    return {
        "code": code,
        "message": message,
        "data": data
    }
