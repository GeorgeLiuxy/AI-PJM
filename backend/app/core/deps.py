"""FastAPI dependency functions"""

from typing import Optional
from fastapi import Header


async def get_operator_ref(
    x_operator_ref: Optional[str] = Header(None, alias="X-Operator-Ref")
) -> Optional[str]:
    """
    Get operator reference from request header.

    This dependency extracts the operator reference from the X-Operator-Ref header.
    If not provided, returns None (will use default in service layer).

    Args:
        x_operator_ref: Operator reference from header

    Returns:
        Operator reference string or None
    """
    return x_operator_ref
