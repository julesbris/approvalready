"""Post-checks on AI output, after schema validation.

The model only rewords what the input already says (ARCHITECTURE.md §1). These checks make
that enforceable rather than hoped for:

* every point cites at least one finding, and only findings that were in the input;
* every fact key a grant draft cites was in the input;
* no number appears in the output that does not appear in the input. Fees, dates, clause
  and section numbers, lot sizes, percentages and amounts all carry digits, so an invented
  one is caught here;
* no link appears that was not in the input.

Output that fails is stored as ``REJECTED`` with the reasons and never shown as a draft.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterable, Iterator
from typing import Any

from pydantic import BaseModel

from app.modules.ai.outputs import AssessmentExplanationV1, GrantDraftV1

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)
_URL = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield str(k)
            yield from _strings(v)
    elif isinstance(value, list | tuple):
        for v in value:
            yield from _strings(v)
    elif value is not None and not isinstance(value, bool):
        yield str(value)


def _numbers(texts: Iterable[str]) -> set[str]:
    found: set[str] = set()
    for t in texts:
        # Ids are not facts: digits inside them must not count as numbers the input gave.
        for match in _NUMBER.findall(_UUID.sub(" ", t)):
            found.add(_normal_number(match))
            # "1,200.50" also yields its parts, so "1,200" and "1200" both match it.
            for part in re.split(r"[.,]", match):
                found.add(_normal_number(part))
    return found


def _normal_number(raw: str) -> str:
    digits = raw.replace(",", "")
    if "." in digits:
        whole, _, frac = digits.partition(".")
        frac = frac.rstrip("0")
        digits = f"{whole}.{frac}" if frac else whole
    return digits.lstrip("0") or "0"


def _urls(texts: Iterable[str]) -> set[str]:
    return {u.rstrip(".,;:").rstrip("/").lower() for t in texts for u in _URL.findall(t)}


def _output_text(output: BaseModel) -> list[str]:
    """Free text the customer will read (not the ids and keys used for citations)."""
    data = output.model_dump(mode="json")

    def drop_refs(v: Any) -> Any:
        if isinstance(v, dict):
            return {k: drop_refs(x) for k, x in v.items() if k not in ("finding_ids", "fact_keys")}
        if isinstance(v, list):
            return [drop_refs(x) for x in v]
        return v

    return list(_strings(drop_refs(data)))


def check_grounding(output: BaseModel, input_data: dict[str, Any]) -> list[str]:
    """Numbers and links in the output must come from the input."""
    input_texts = list(_strings(input_data))
    errors: list[str] = []
    allowed_numbers = _numbers(input_texts)
    for text in _output_text(output):
        for raw in _NUMBER.findall(text):
            if _normal_number(raw) not in allowed_numbers:
                errors.append(f"The number {raw!r} is not in the input: {text[:120]!r}")
    allowed_urls = _urls(input_texts)
    for text in _output_text(output):
        for url in _urls([text]):
            if url not in allowed_urls:
                errors.append(f"The link {url!r} is not in the input")
    return errors


def _cited(ids: Iterable[uuid.UUID], allowed: set[str], where: str) -> list[str]:
    return [
        f"{where} cites a finding that is not in the input: {i}"
        for i in ids
        if str(i) not in allowed
    ]


def check_explanation(output: AssessmentExplanationV1, input_data: dict[str, Any]) -> list[str]:
    allowed = {f["id"] for f in input_data.get("findings", [])}
    errors: list[str] = []
    for name in ("points", "next_steps", "open_questions"):
        for n, point in enumerate(getattr(output, name), start=1):
            errors += _cited(point.finding_ids, allowed, f"{name} {n}")
    return errors + check_grounding(output, input_data)


def check_grant_draft(output: GrantDraftV1, input_data: dict[str, Any]) -> list[str]:
    allowed = {c["finding_id"] for c in input_data.get("criteria", []) if c.get("finding_id")}
    facts = {f["key"] for f in input_data.get("applicant_facts", [])}
    errors: list[str] = []
    for n, section in enumerate(output.sections, start=1):
        if not section.finding_ids and not section.fact_keys:
            errors.append(f"section {n} cites no criterion and no applicant fact")
        errors += _cited(section.finding_ids, allowed, f"section {n}")
        errors += [
            f"section {n} cites a fact that is not in the input: {k}"
            for k in section.fact_keys
            if k not in facts
        ]
    return errors + check_grounding(output, input_data)


def canonical(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
