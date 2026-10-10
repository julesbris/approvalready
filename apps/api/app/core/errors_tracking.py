"""Error tracking (Milestone 17): unhandled errors in the API and the worker are reported to
Sentry, or any service that speaks its protocol (GlitchTip can be self-hosted), when
``SENTRY_DSN`` is set. Off by default.

Reports carry the stack trace, the route and the request id, never personal data: no
cookies, headers, request bodies, query strings, user details or IP addresses, and no
performance tracing.
"""

from __future__ import annotations

from typing import Any

from app.core.config import Settings

_KEEP_HEADERS = {"user-agent", "x-request-id"}


def scrub(event: dict[str, Any], hint: dict[str, Any] | None = None) -> dict[str, Any] | None:
    request = event.get("request")
    if isinstance(request, dict):
        headers = request.get("headers")
        if isinstance(headers, dict):
            request["headers"] = {
                k: v for k, v in headers.items() if str(k).lower() in _KEEP_HEADERS
            }
        for key in ("cookies", "data", "query_string", "env"):
            request.pop(key, None)
    event.pop("user", None)
    return event


def init_error_tracking(settings: Settings, component: str) -> bool:
    if settings.sentry_dsn is None:
        return False
    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn.get_secret_value(),
        environment=settings.app_env.value,
        release=settings.git_sha if settings.git_sha != "unknown" else settings.app_version,
        server_name=component,
        send_default_pii=False,
        include_local_variables=False,
        traces_sample_rate=0.0,
        before_send=scrub,  # type: ignore[arg-type]
    )
    sentry_sdk.set_tag("component", component)
    return True
