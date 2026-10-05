"""Password hashing, opaque token generation and CSRF token derivation.

Tokens (sessions, email verification, password reset, invitations) are 256-bit random
values. Only their SHA-256 digest is stored, so a database leak does not yield usable
tokens. SHA-256 (not a slow hash) is appropriate because the input has full entropy.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# argon2-cffi defaults follow RFC 9106's second recommended profile (Argon2id, 64 MiB).
_hasher = PasswordHasher()

# Verified against when the account does not exist, so response time does not reveal
# whether an email address is registered.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(32))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def csrf_token_for(secret_key: str, session_id: uuid.UUID) -> str:
    """CSRF token bound to a session (HMAC), stable across session-token rotation."""
    mac = hmac.new(secret_key.encode(), b"csrf:" + session_id.bytes, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).rstrip(b"=").decode()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
