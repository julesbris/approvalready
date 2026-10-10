"""Encryption at rest for small secrets the application must read back (TOTP seeds).

AES-256-GCM with a key derived from SECRET_KEY by HKDF, separately for each purpose. The
purpose is also the associated data, so a value sealed for one purpose can't be opened as
another. Changing SECRET_KEY makes sealed values unreadable: two-step sign-in then has to be
reset for each user (``python -m app.cli auth reset-mfa``).
"""

from __future__ import annotations

import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_VERSION = b"\x01"
_NONCE_BYTES = 12


class SealedValueError(ValueError):
    """The value was not sealed with this key and purpose, or has been altered."""


def _key(secret_key: str, purpose: str) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"approvalready:" + purpose.encode(),
    ).derive(secret_key.encode())


def seal(secret_key: str, purpose: str, plaintext: bytes) -> bytes:
    nonce = os.urandom(_NONCE_BYTES)
    sealed = AESGCM(_key(secret_key, purpose)).encrypt(nonce, plaintext, purpose.encode())
    return _VERSION + nonce + sealed


def unseal(secret_key: str, purpose: str, value: bytes) -> bytes:
    if len(value) < 1 + _NONCE_BYTES + 16 or value[:1] != _VERSION:
        raise SealedValueError("unknown format")
    nonce, sealed = value[1 : 1 + _NONCE_BYTES], value[1 + _NONCE_BYTES :]
    try:
        return AESGCM(_key(secret_key, purpose)).decrypt(nonce, sealed, purpose.encode())
    except InvalidTag as exc:
        raise SealedValueError("cannot open") from exc
