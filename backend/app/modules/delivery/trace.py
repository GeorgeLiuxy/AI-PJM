"""Trace id helpers for delivery workflow records."""

from __future__ import annotations

import uuid


def generate_delivery_trace_id() -> str:
    return f"dlv-{uuid.uuid4().hex[:20]}"
