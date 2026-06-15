"""Sensitive data redaction helpers for delivery evidence and logs."""

from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"
_MASKED_SECRET_VALUES = {
    "",
    REDACTED.lower(),
    "redacted",
    "<redacted>",
    "***",
    "****",
    "********",
}

_SENSITIVE_KEY_VALUE_RE = re.compile(
    r"(?i)\b("
    r"[a-z0-9_-]*(?:api[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|"
    r"auth[_-]?token|token|secret|password|passwd|pwd|"
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
_URL_USERINFO_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^:/\s@]+:)([^@\s/]+)(@)")
_AUTH_HEADER_RE = re.compile(r"(?i)\b(authorization\s*[:=]\s*)([^\r\n]+)")
_BEARER_RE = re.compile(r"(?i)\b(bearer\s+)([a-z0-9._~+/=-]{8,})")
_PEM_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----"
)
_KNOWN_SECRET_RES = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bgl(?:pat|rt|dt|cbt|ptt|soat|agent)-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bgh[ophsru]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bxox[abcpres]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bxapp-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bapp-[A-Za-z0-9]{24,}\b"),
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

    text = _PEM_PRIVATE_KEY_RE.sub(REDACTED, text)
    text = _URL_USERINFO_RE.sub(lambda match: f"{match.group(1)}{REDACTED}{match.group(3)}", text)
    text = _AUTH_HEADER_RE.sub(
        lambda match: match.group(0)
        if _is_masked_secret_text(match.group(2))
        else f"{match.group(1)}{REDACTED}",
        text,
    )
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


def has_unredacted_sensitive_data(value: Any) -> bool:
    """Return True when a value appears to contain plaintext secrets."""

    if value is None:
        return False
    if isinstance(value, dict):
        for key, item in value.items():
            if _is_sensitive_key(key) and _sensitive_key_value_is_plaintext(item):
                return True
            if has_unredacted_sensitive_data(item):
                return True
        return False
    if isinstance(value, list | tuple):
        return any(has_unredacted_sensitive_data(item) for item in value)
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
        return redact_text(text) != text
    if isinstance(value, str):
        return redact_text(value) != value
    return False


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


def _sensitive_key_value_is_plaintext(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, dict | list | tuple):
        return has_unredacted_sensitive_data(value)
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return not _is_masked_secret_text(value)
    return True


def _is_masked_secret_text(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in _MASKED_SECRET_VALUES:
        return True
    if normalized.startswith("bearer "):
        return normalized.removeprefix("bearer ").strip() in _MASKED_SECRET_VALUES
    return False
