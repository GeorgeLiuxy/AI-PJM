"""Encryption helpers for the local secret store."""

from __future__ import annotations

import base64
import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings
from app.core.exceptions import BadRequestException


def _fernet() -> Fernet:
    master_key = settings.secret_store_master_key.strip()
    if not master_key:
        raise BadRequestException("SECRET_STORE_MASTER_KEY is required before storing secrets")
    key = base64.urlsafe_b64encode(hashlib.sha256(master_key.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    """Encrypt a secret value for storage."""

    if not value:
        raise BadRequestException("Secret value is required")
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    """Decrypt a secret value for server-side use only."""

    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise BadRequestException("Secret cannot be decrypted with the configured key") from exc


def secret_fingerprint(value: str) -> str:
    """Return a keyed fingerprint used for rotation checks."""

    master_key = settings.secret_store_master_key.strip()
    if not master_key:
        raise BadRequestException("SECRET_STORE_MASTER_KEY is required before storing secrets")
    return hmac.new(master_key.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()


def mask_secret(value: str) -> str:
    """Return a non-sensitive display mask."""

    if len(value) <= 4:
        return "****"
    return f"****{value[-4:]}"
