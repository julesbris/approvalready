"""Uniform API errors: ``{"detail": {"code": "...", "message": "...", "fields"?: {...}}}``.

``code`` is stable and machine-readable (the web app branches on it); ``message`` is a
human-readable English sentence safe to show to the user.
"""

from __future__ import annotations

from fastapi import HTTPException, status


class ApiError(HTTPException):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        headers: dict[str, str] | None = None,
        fields: dict[str, str] | None = None,
    ) -> None:
        detail: dict[str, object] = {"code": code, "message": message}
        if fields:
            # Per-field messages (e.g. questionnaire answers), keyed by field or question key.
            detail["fields"] = fields
        super().__init__(status_code, detail, headers)
        self.code = code


def unauthenticated() -> ApiError:
    return ApiError(status.HTTP_401_UNAUTHORIZED, "unauthenticated", "Please sign in.")


def forbidden(message: str = "You do not have permission to do that.") -> ApiError:
    return ApiError(status.HTTP_403_FORBIDDEN, "forbidden", message)


def not_found(what: str = "Resource") -> ApiError:
    return ApiError(status.HTTP_404_NOT_FOUND, "not_found", f"{what} not found.")


def rate_limited(retry_after: int) -> ApiError:
    return ApiError(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "rate_limited",
        "Too many attempts. Please wait and try again.",
        headers={"retry-after": str(retry_after)},
    )
