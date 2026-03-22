"""Common utility functions"""

from typing import Any
from datetime import datetime, timezone


def utc_now() -> datetime:
    """Get current UTC timestamp"""
    return datetime.now(timezone.utc)


def model_to_dict(model: Any) -> dict[str, Any] | None:
    """
    Convert SQLAlchemy model to dictionary.

    Args:
        model: SQLAlchemy model instance

    Returns:
        Dictionary representation of the model, or None if model is None
    """
    if model is None:
        return None

    result = {}
    for column in model.__table__.columns:
        value = getattr(model, column.name)
        if isinstance(value, datetime):
            value = value.isoformat()
        result[column.name] = value
    return result


def snake_to_camel(s: str) -> str:
    """Convert snake_case to camelCase"""
    components = s.split('_')
    return components[0] + ''.join(x.title() for x in components[1:])


def camel_to_snake(s: str) -> str:
    """Convert camelCase to snake_case"""
    import re
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', s)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
