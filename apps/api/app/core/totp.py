"""Time-based one-time passwords (RFC 6238: HMAC-SHA1, 6 digits, 30-second steps).

These are the codes authenticator apps (Google Authenticator, Microsoft Authenticator,
1Password, Authy) show. Verification accepts the previous, current and next step to allow
for clock drift, and the caller stores the last accepted step so a code can't be replayed.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode

import segno

STEP_SECONDS = 30
DIGITS = 6
DRIFT_STEPS = 1
SECRET_BYTES = 20  # 160 bits, as RFC 4226 recommends


def new_secret() -> str:
    """A base32 secret (no padding), the form authenticator apps accept."""
    return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode().rstrip("=")


def _key(secret: str) -> bytes:
    padded = secret.upper() + "=" * (-len(secret) % 8)
    return base64.b32decode(padded)


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // STEP_SECONDS)


def code_at(secret: str, step: int) -> str:
    digest = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**DIGITS).zfill(DIGITS)


def normalise_code(code: str) -> str:
    return "".join(ch for ch in code if not ch.isspace() and ch != "-")


def matching_step(
    secret: str, code: str, *, after_step: int | None = None, now: float | None = None
) -> int | None:
    """The step ``code`` belongs to (within the drift window), or None. Steps at or before
    ``after_step`` (the last code already used) never match, so codes can't be replayed."""
    code = normalise_code(code)
    if len(code) != DIGITS or not code.isdigit():
        return None
    step = current_step(now)
    for candidate in range(step - DRIFT_STEPS, step + DRIFT_STEPS + 1):
        if after_step is not None and candidate <= after_step:
            continue
        if hmac.compare_digest(code_at(secret, candidate), code):
            return candidate
    return None


def provisioning_uri(secret: str, account: str, issuer: str) -> str:
    label = quote(f"{issuer}:{account}", safe="@:")
    query = urlencode(
        {
            "secret": secret,
            "issuer": issuer,
            "algorithm": "SHA1",
            "digits": DIGITS,
            "period": STEP_SECONDS,
        }
    )
    return f"otpauth://totp/{label}?{query}"


def qr_svg(uri: str) -> str:
    """The provisioning URI as an SVG QR code (dark modules on a white quiet zone)."""
    qr = segno.make(uri, error="m", micro=False)
    return str(qr.svg_inline(scale=4, border=4, dark="#000", light="#fff", omitsize=True))
