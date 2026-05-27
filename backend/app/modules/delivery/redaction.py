"""Sensitive data redaction helpers for delivery evidence and logs."""

from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"

_SENSITIVE_KEY_VALUE_RE = re.compile(
    r"(?i)\b("
    r"[a-z0-9_-]*(?:api[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|"
    r"auth[_-]?token|token|secret|password|passwd|pwd|authorization|"
    r"client[_-]?secret|private[_-]?key)[a-z0-9_-]*"
    r"\s*[:=]\s*)(['\"]?)([^\s'\",;&|]+)(['\"]?)"
)
_CLI_SECRET_ARG_RE = re.compile(
    r"(?i)(--(?:api[-_]?key|access[-_]?token|refresh[-_]?token|id[-_]?token|"
    r"auth[-_]?token|token|secret|password|client[-_]?secret|private[-_]?key)"
    r"(?:\s+|=))(['\"]?)([^\s'\"]+)(['\"]?)"
)
_URL_SECRET_PARAM_RE = re.compile(
    r"(?i)([?&](?:api[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|"
    r"auth[_-]?token|token|secret|password|client[_-]?secret)=)([^&#\s]+)"
)
_AUTH_HEADER_RE = re.compile(r"(?i)\b(authorization\s*[:=]\s*)([^\r\n]+)")
_BEARER_RE = re.compile(r"(?i)\b(bearer\s+)([a-z0-9._~+/=-]{8,})")
_KNOWN_SECRET_RES = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bapjm_[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
]
_SENSITIVE_KEY_EXACT = {
    "apikey",
    "authorization",
    "authtoken",
    "bearertoken",
    "clientsecret",
    "idtoken",
    "password",
    "passwd",
    "privatekey",
    "pwd",
    "refreshtoken",
    "secret",
    "token",
}
_SENSITIVE_KEY_MARKERS = (
    "accesstoken",
    "authtoken",
    "bearertoken",
    "clientsecret",
    "idtoken",
    "privatekey",
    "refreshtoken",
)


def redact_text(value: str | bytes | None) -> str:
    """Redact likely secrets from a free-form text value."""

    if value is None:
        return ""
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
    if not text:
        return text

    text = _AUTH_HEADER_RE.sub(lambda match: f"{match.group(1)}{REDACTED}", text)
    text = _SENSITIVE_KEY_VALUE_RE.sub(lambda match: f"{match.group(1)}{REDACTED}", text)
    text = _CLI_SECRET_ARG_RE.sub(lambda match: f"{match.group(1)}{REDACTED}", text)
    text = _URL_SECRET_PARAM_RE.sub(lambda match: f"{match.group(1)}{REDACTED}", text)
    text = _BEARER_RE.sub(lambda match: f"{match.group(1)}{REDACTED}", text)
    for pattern in _KNOWN_SECRET_RES:
        text = pattern.sub(REDACTED, text)
    return text


def redact_value(value: Any) -> Any:
    """Recursively redact likely secrets from JSON-like values."""

    if isinstance(value, dict):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            if _is_sensitive_key(key) and item is not None:
                redacted[key] = REDACTED
            else:
                redacted[key] = redact_value(item)
        return redacted
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    if isinstance(value, bytes | str):
        return redact_text(value)
    return value


def _is_sensitive_key(key: Any) -> bool:
    if not isinstance(key, str):
        return False

    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    if not normalized:
        return False
    if normalized.endswith(("secretname", "tokenname", "keyname")):
        return False
    if normalized in _SENSITIVE_KEY_EXACT:
        return True
    if any(marker in normalized for marker in _SENSITIVE_KEY_MARKERS):
        return True
    return normalized.endswith(("apikey", "authorization", "password", "secret", "token"))
