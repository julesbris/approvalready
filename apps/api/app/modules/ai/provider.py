"""The ``AIProvider`` protocol and its implementations.

A provider turns one prepared request (system prompt, user message with the data block,
output schema) into JSON, and reports what the call cost. It never sees the database, has
no tools, and cannot change anything: whatever it returns is validated and post-checked by
the caller (``service.py``) before anyone reads it.

* ``none``: AI is off. Every call fails with ``AIDisabled`` (the UI hides the buttons).
* ``mock``: builds a deterministic answer from the data block, for development and tests.
  Refused in production (``config.py``).
* ``anthropic``: Claude through the Anthropic API, with JSON structured output.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.core.config import AIProviderKind, Settings


@dataclass(frozen=True)
class StructuredRequest:
    task: str
    system: str
    user: str
    schema: dict[str, Any]
    # The same data that is serialised into ``user``. Only the mock provider reads it.
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderResult:
    output: dict[str, Any]
    model: str
    request_tokens: int | None
    response_tokens: int | None
    latency_ms: int


class ProviderError(Exception):
    """The call failed for good (bad request, declined, unusable answer)."""

    def __init__(
        self,
        message: str,
        *,
        model: str = "",
        refused: bool = False,
        request_tokens: int | None = None,
        response_tokens: int | None = None,
    ) -> None:
        super().__init__(message)
        self.model = model
        self.refused = refused
        self.request_tokens = request_tokens
        self.response_tokens = response_tokens


class TransientProviderError(ProviderError):
    """Worth retrying later (rate limit, overload, network)."""


class AIDisabled(ProviderError):
    pass


class AIProvider(Protocol):
    name: str
    model: str

    async def generate_structured(self, request: StructuredRequest) -> ProviderResult: ...

    async def generate_text(self, system: str, user: str) -> str: ...


class DisabledProvider:
    name = "none"
    model = "none"

    async def generate_structured(self, request: StructuredRequest) -> ProviderResult:
        raise AIDisabled("AI drafting is switched off on this server.")

    async def generate_text(self, system: str, user: str) -> str:
        raise AIDisabled("AI drafting is switched off on this server.")


class MockProvider:
    """Answers from the data block alone, so its output always passes the post-checks.
    Clearly labelled: every text it writes starts with ``[MOCK]``."""

    name = "mock"
    model = "mock-1"

    async def generate_structured(self, request: StructuredRequest) -> ProviderResult:
        started = time.monotonic()
        if request.task == "ASSESSMENT_EXPLANATION":
            output = _mock_explanation(request.data)
        elif request.task == "GRANT_DRAFT":
            output = _mock_grant_draft(request.data)
        else:
            raise ProviderError(f"the mock provider has no answer for {request.task}")
        return ProviderResult(
            output=output,
            model=self.model,
            request_tokens=len(request.system + request.user) // 4,
            response_tokens=len(json.dumps(output)) // 4,
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    async def generate_text(self, system: str, user: str) -> str:
        return "[MOCK] " + user[:200]


_RESULT_WORDS = {
    "MATCH": "applies to your project",
    "NO_MATCH": "does not apply to your project",
    "UNKNOWN": "could not be decided from your answers yet",
}


def _mock_explanation(data: dict[str, Any]) -> dict[str, Any]:
    findings = data.get("findings", [])
    points = [
        {
            "text": f"[MOCK] {f.get('title') or f['rule_title']}: this "
            f"{_RESULT_WORDS.get(f['result'], 'was checked')}.",
            "finding_ids": [f["id"]],
        }
        for f in findings
    ]
    open_questions = [
        {
            "text": f"[MOCK] Answer: {', '.join(f['missing_facts'])}.",
            "finding_ids": [f["id"]],
        }
        for f in findings
        if f.get("missing_facts")
    ]
    return {
        "summary": "[MOCK] A plain-language summary of the findings below.",
        "points": points or [],
        "next_steps": [],
        "open_questions": open_questions,
    }


def _mock_grant_draft(data: dict[str, Any]) -> dict[str, Any]:
    facts = data.get("applicant_facts", [])
    sections = [
        {
            "heading": f"[MOCK] {c['title']}",
            "text": f"[MOCK] How the applicant meets: {c['title']}.",
            "finding_ids": [c["finding_id"]],
            "fact_keys": [],
        }
        for c in data.get("criteria", [])
        if c.get("finding_id")
    ]
    if facts:
        sections.insert(
            0,
            {
                "heading": "[MOCK] About the applicant",
                "text": "[MOCK] " + "; ".join(f"{f['label']}: {f['value']}" for f in facts[:10]),
                "fact_keys": [f["key"] for f in facts[:10]],
                "finding_ids": [],
            },
        )
    return {
        "sections": sections
        or [
            {
                "heading": "[MOCK]",
                "text": "[MOCK]",
                "finding_ids": [],
                "fact_keys": [facts[0]["key"]] if facts else [],
            }
        ],
        "missing_information": [f"[MOCK] {m}" for m in data.get("missing_facts", [])][:20],
    }


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, settings: Settings) -> None:
        from anthropic import AsyncAnthropic

        assert settings.anthropic_api_key is not None  # checked by config in production
        self.model = settings.ai_model
        self.effort = settings.ai_effort
        self.max_tokens = settings.ai_max_output_tokens
        self.fallback = settings.ai_refusal_fallback
        self.client = AsyncAnthropic(
            api_key=settings.anthropic_api_key.get_secret_value(),
            timeout=settings.ai_timeout_seconds,
            max_retries=2,
        )

    async def _create(self, system: str, user: str, schema: dict[str, Any] | None) -> Any:
        output_config: dict[str, Any] = {"effort": self.effort}
        if schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            # The system prompt is the same for every job of a task: cache it.
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": user}],
            "output_config": output_config,
        }
        if self.fallback:
            return await self.client.beta.messages.create(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
            )
        return await self.client.messages.create(**kwargs)

    async def _call(
        self, system: str, user: str, schema: dict[str, Any] | None
    ) -> tuple[str, Any, int]:
        import anthropic

        started = time.monotonic()
        try:
            response = await self._create(system, user, schema)
        except (anthropic.RateLimitError, anthropic.InternalServerError) as exc:
            raise TransientProviderError(_short(exc), model=self.model) from exc
        except anthropic.APIConnectionError as exc:
            raise TransientProviderError(
                "Could not reach the AI provider.", model=self.model
            ) from exc
        except anthropic.APIStatusError as exc:
            raise ProviderError(_short(exc), model=self.model) from exc
        latency = int((time.monotonic() - started) * 1000)
        usage = getattr(response, "usage", None)
        tokens_in = getattr(usage, "input_tokens", None)
        tokens_out = getattr(usage, "output_tokens", None)
        model = str(getattr(response, "model", self.model))
        if response.stop_reason == "refusal":
            raise ProviderError(
                "The AI provider declined this request.",
                model=model,
                refused=True,
                request_tokens=tokens_in,
                response_tokens=tokens_out,
            )
        if response.stop_reason == "max_tokens":
            raise ProviderError(
                "The answer was cut off before it was complete.",
                model=model,
                request_tokens=tokens_in,
                response_tokens=tokens_out,
            )
        text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
        return text, (model, tokens_in, tokens_out), latency

    async def generate_structured(self, request: StructuredRequest) -> ProviderResult:
        text, (model, tokens_in, tokens_out), latency = await self._call(
            request.system, request.user, request.schema
        )
        try:
            output = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProviderError(
                "The answer was not valid JSON.",
                model=model,
                request_tokens=tokens_in,
                response_tokens=tokens_out,
            ) from exc
        if not isinstance(output, dict):
            raise ProviderError("The answer was not a JSON object.", model=model)
        return ProviderResult(output, model, tokens_in, tokens_out, latency)

    async def generate_text(self, system: str, user: str) -> str:
        text, _, _ = await self._call(system, user, None)
        return text


def _short(exc: Exception) -> str:
    status = getattr(exc, "status_code", None)
    prefix = f"AI provider error {status}" if status else "AI provider error"
    return f"{prefix}: {type(exc).__name__}"


def create_provider(settings: Settings) -> AIProvider:
    if settings.ai_provider == AIProviderKind.MOCK:
        return MockProvider()
    if settings.ai_provider == AIProviderKind.ANTHROPIC and settings.anthropic_api_key:
        return AnthropicProvider(settings)
    return DisabledProvider()
