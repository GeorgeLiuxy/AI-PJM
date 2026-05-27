"""Password and token helpers for local auth."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets


PASSWORD_HASH_PREFIX = "pbkdf2_sha256"
PASSWORD_HASH_ITERATIONS = 260_000


def hash_password(password: str) -> str:
    """Hash a password with PBKDF2-HMAC-SHA256."""

    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_HASH_ITERATIONS,
    )
    return "$".join(
        [
            PASSWORD_HASH_PREFIX,
            str(PASSWORD_HASH_ITERATIONS),
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(digest).decode("ascii"),
        ]
    )


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against a stored PBKDF2 hash."""

    try:
        prefix, iterations, salt_b64, digest_b64 = stored_hash.split("$", 3)
        if prefix != PASSWORD_HASH_PREFIX:
            return False
        salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_b64.encode("ascii"))
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            int(iterations),
        )
    except (ValueError, TypeError):
        return False

    return hmac.compare_digest(actual, expected)


def generate_api_token() -> str:
    """Generate a bearer token suitable for browser and CLI use."""

    return f"apjm_{secrets.token_urlsafe(32)}"


def hash_api_token(token: str) -> str:
    """Hash an API token before storing it."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()

