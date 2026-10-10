"""Output schemas the model must fill, by name and version.

Each prompt file names the schema its answer must match. The provider is asked for JSON in
that shape (``json_schema``), and the answer is then validated with the Pydantic model
here, which also carries the length limits. A new shape is a new version: stored jobs keep
the version they were made with.
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Sentence = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
Paragraph = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2500)]


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CitedPoint(_Out):
    text: Sentence = Field(description="One plain-language point.")
    finding_ids: list[uuid.UUID] = Field(
        min_length=1,
        max_length=20,
        description="The findings this point explains, by id, copied exactly from the input.",
    )


class AssessmentExplanationV1(_Out):
    summary: Paragraph = Field(
        description="Two or three sentences on what the assessment found overall."
    )
    points: list[CitedPoint] = Field(
        min_length=1, max_length=30, description="What each finding means for the customer."
    )
    next_steps: list[CitedPoint] = Field(
        max_length=15, description="What the findings say to do next, if anything."
    )
    open_questions: list[CitedPoint] = Field(
        max_length=15,
        description="Facts the findings are missing that the customer could answer.",
    )


class DraftSection(_Out):
    heading: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    text: Paragraph
    finding_ids: list[uuid.UUID] = Field(
        max_length=20, description="Criteria this section addresses, by finding id."
    )
    fact_keys: list[str] = Field(
        max_length=30, description="Applicant facts this section uses, by key."
    )


class GrantDraftV1(_Out):
    sections: list[DraftSection] = Field(min_length=1, max_length=12)
    missing_information: list[Sentence] = Field(
        max_length=20, description="What the applicant still needs to provide."
    )


@dataclass(frozen=True)
class OutputSchema:
    name: str
    version: int
    model: type[_Out]

    def json_schema(self) -> dict[str, Any]:
        return strict_json_schema(self.model)


SCHEMAS: dict[tuple[str, int], OutputSchema] = {
    (s.name, s.version): s
    for s in (
        OutputSchema("assessment_explanation", 1, AssessmentExplanationV1),
        OutputSchema("grant_draft", 1, GrantDraftV1),
    )
}


def get_schema(name: str, version: int) -> OutputSchema:
    try:
        return SCHEMAS[(name, version)]
    except KeyError:
        raise ValueError(f"unknown output schema {name} v{version}") from None


# Structured outputs accept a subset of JSON Schema. Constraints the API does not take
# (lengths, item counts) are dropped here and enforced by Pydantic afterwards.
_KEEP = {"type", "properties", "required", "items", "enum", "description", "anyOf", "format"}


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    raw = model.model_json_schema()
    defs = raw.get("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(copy.deepcopy(defs[node["$ref"].split("/")[-1]]))
            out = {k: walk(v) for k, v in node.items() if k in _KEEP}
            if out.get("format") not in (None, "uuid"):
                out.pop("format")
            if out.get("type") == "object":
                out["additionalProperties"] = False
                out["required"] = sorted(out.get("properties", {}))
            return out
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    schema: dict[str, Any] = walk({k: v for k, v in raw.items() if k != "$defs"})
    return schema
