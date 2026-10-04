"""Questionnaire definition documents (the JSON files in ``definitions/``).

A definition is validated completely before anything is written: question keys unique,
options only where they make sense, validation settings that fit the question type, and
``visible_when`` conditions that only reference questions asked *earlier* in the same
questionnaire (so branching can never form a cycle) with operators that suit those
questions' types.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from app.modules.conditions.ast import (
    LIST_OPS,
    ORDER_OPS,
    All,
    AnyOf,
    Leaf,
    Not,
    Op,
    dump_condition,
    parse_condition,
    referenced_facts,
)
from app.modules.projects.models import Vertical
from app.modules.questionnaires.models import KEY_PATTERN, QuestionType

DEFINITIONS_DIR = Path(__file__).parent / "definitions"

QT = QuestionType
OPTION_TYPES = frozenset({QT.SELECT, QT.MULTISELECT})
NUMERIC_TYPES = frozenset({QT.NUMBER, QT.DECIMAL, QT.CURRENCY})
TEXT_TYPES = frozenset({QT.TEXT, QT.TEXTAREA})

# Which validation settings each question type accepts.
ALLOWED_VALIDATION: dict[QuestionType, frozenset[str]] = {
    QT.TEXT: frozenset({"min_length", "max_length", "pattern", "pattern_message"}),
    QT.TEXTAREA: frozenset({"min_length", "max_length"}),
    QT.NUMBER: frozenset({"min", "max"}),
    QT.DECIMAL: frozenset({"min", "max", "max_decimal_places"}),
    QT.CURRENCY: frozenset({"min", "max"}),
    QT.BOOLEAN: frozenset(),
    QT.SELECT: frozenset(),
    QT.MULTISELECT: frozenset({"min_items", "max_items"}),
    QT.DATE: frozenset({"min_date", "max_date"}),
    QT.ADDRESS: frozenset(),
    QT.FILE: frozenset({"max_files"}),
    QT.OBJECT: frozenset({"fields"}),
}

# Sub-facts exposed by structured answers (``<question key>.<field>``).
ADDRESS_FIELDS: dict[str, QuestionType] = {
    "line1": QT.TEXT,
    "line2": QT.TEXT,
    "suburb": QT.TEXT,
    "state": QT.SELECT,
    "postcode": QT.TEXT,
}

DEFAULT_MAX_LENGTH = {QT.TEXT: 200, QT.TEXTAREA: 5000}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OptionDef(_Strict):
    value: str = Field(pattern=r"^[A-Za-z0-9_]{1,100}$")
    label: str = Field(min_length=1, max_length=200)


class FieldDef(_Strict):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    label: str = Field(min_length=1, max_length=200)
    type: Literal["TEXT", "NUMBER", "DECIMAL", "BOOLEAN", "DATE"]
    required: bool = False


class ValidationDef(_Strict):
    min_length: int | None = Field(default=None, ge=0, le=20_000)
    max_length: int | None = Field(default=None, ge=1, le=20_000)
    pattern: str | None = Field(default=None, max_length=200)
    pattern_message: str | None = Field(default=None, max_length=200)
    min: Decimal | None = None
    max: Decimal | None = None
    max_decimal_places: int | None = Field(default=None, ge=0, le=10)
    min_items: int | None = Field(default=None, ge=0, le=100)
    max_items: int | None = Field(default=None, ge=1, le=100)
    min_date: date | None = None
    max_date: date | None = None
    max_files: int | None = Field(default=None, ge=1, le=20)
    fields: list[FieldDef] | None = Field(default=None, min_length=1, max_length=20)

    @field_validator("pattern")
    @classmethod
    def _compiles(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                re.compile(value)
            except re.error as exc:
                raise ValueError(f"invalid pattern: {exc}") from None
        return value

    @model_validator(mode="after")
    def _ranges(self) -> ValidationDef:
        pairs = [
            (self.min_length, self.max_length),
            (self.min, self.max),
            (self.min_items, self.max_items),
            (self.min_date, self.max_date),
        ]
        for low, high in pairs:
            if low is not None and high is not None and low > high:  # type: ignore[operator]
                raise ValueError("a minimum is greater than its maximum")
        if self.fields is not None and len({f.key for f in self.fields}) != len(self.fields):
            raise ValueError("object field keys must be unique")
        return self

    def settings(self) -> set[str]:
        return {k for k, v in self.model_dump().items() if v is not None}


class QuestionDef(_Strict):
    key: str = Field(pattern=KEY_PATTERN, max_length=120)
    type: QuestionType
    label: str = Field(min_length=1, max_length=300)
    help_text: str | None = Field(default=None, max_length=1000)
    required: bool = False
    options: list[OptionDef] = Field(default_factory=list, max_length=100)
    validation: ValidationDef = Field(default_factory=ValidationDef)
    visible_when: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _shape(self) -> QuestionDef:
        if self.type in OPTION_TYPES:
            if len(self.options) < 2:
                raise ValueError(f"{self.key}: {self.type} questions need at least two options")
            if len({o.value for o in self.options}) != len(self.options):
                raise ValueError(f"{self.key}: option values must be unique")
        elif self.options:
            raise ValueError(f"{self.key}: only SELECT and MULTISELECT questions take options")
        extra = self.validation.settings() - ALLOWED_VALIDATION[self.type]
        if extra:
            raise ValueError(f"{self.key}: {self.type} does not support {sorted(extra)}")
        if self.type == QT.OBJECT and not self.validation.fields:
            raise ValueError(f"{self.key}: OBJECT questions need validation.fields")
        return self

    @field_validator("visible_when")
    @classmethod
    def _condition(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        """Normalise the condition (validates syntax and size limits)."""
        if value is None:
            return None
        try:
            return dump_condition(parse_condition(value))
        except ValidationError as exc:
            raise ValueError(f"invalid visible_when: {exc.errors()[0]['msg']}") from exc

    def fact_types(self) -> dict[str, tuple[QuestionType, frozenset[str]]]:
        """Fact paths this question provides, with their type and allowed option values."""
        options = frozenset(o.value for o in self.options)
        facts: dict[str, tuple[QuestionType, frozenset[str]]] = {self.key: (self.type, options)}
        if self.type == QT.ADDRESS:
            states = frozenset({"NSW", "VIC", "QLD", "SA", "WA", "TAS", "NT", "ACT"})
            for name, ftype in ADDRESS_FIELDS.items():
                facts[f"{self.key}.{name}"] = (ftype, states if name == "state" else frozenset())
        for field in self.validation.fields or []:
            facts[f"{self.key}.{field.key}"] = (QuestionType(field.type), frozenset())
        return facts


class SectionDef(_Strict):
    title: str = Field(min_length=1, max_length=120)
    questions: list[QuestionDef] = Field(min_length=1, max_length=100)


class QuestionnaireDef(_Strict):
    key: str = Field(pattern=KEY_PATTERN, max_length=100)
    vertical: Vertical
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    sections: list[SectionDef] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def _references(self) -> QuestionnaireDef:
        seen: dict[str, tuple[QuestionType, frozenset[str]]] = {}
        titles = [s.title for s in self.sections]
        if len(set(titles)) != len(titles):
            raise ValueError("section titles must be unique")
        for question in self.questions():
            if question.key in seen:
                raise ValueError(f"duplicate question key {question.key}")
            if question.visible_when is not None:
                _check_condition(question.key, parse_condition(question.visible_when), seen)
            seen.update(question.fact_types())
        return self

    def questions(self) -> list[QuestionDef]:
        return [q for s in self.sections for q in s.questions]

    def content_hash(self) -> bytes:
        canonical = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return hashlib.sha256(canonical.encode()).digest()


def _check_condition(
    owner: str,
    node: All | AnyOf | Not | Leaf,
    earlier: dict[str, tuple[QuestionType, frozenset[str]]],
) -> None:
    for leaf in referenced_facts(node):
        if leaf.fact not in earlier:
            raise ValueError(
                f"{owner}: visible_when references {leaf.fact}, which is not asked earlier"
            )
        ftype, options = earlier[leaf.fact]
        values = leaf.value if isinstance(leaf.value, list) else [leaf.value]
        if leaf.op in ORDER_OPS and ftype not in NUMERIC_TYPES | {QT.DATE}:
            raise ValueError(f"{owner}: '{leaf.op}' needs a number or date fact ({leaf.fact})")
        if leaf.op in LIST_OPS and ftype == QT.MULTISELECT:
            raise ValueError(f"{owner}: use 'contains' for multi-select facts ({leaf.fact})")
        if leaf.op in {Op.CONTAINS, Op.NOT_CONTAINS} and ftype not in TEXT_TYPES | {QT.MULTISELECT}:
            raise ValueError(f"{owner}: '{leaf.op}' needs a text or multi-select fact")
        if options and leaf.value is not None:
            unknown = [v for v in values if v not in options]
            if unknown:
                raise ValueError(f"{owner}: {leaf.fact} has no option {unknown[0]!r}")
        if (
            ftype == QT.BOOLEAN
            and leaf.value is not None
            and not all(isinstance(v, bool) for v in values)
        ):
            raise ValueError(f"{owner}: {leaf.fact} is yes/no; compare with true or false")


def load_bundled() -> list[QuestionnaireDef]:
    """Every definition shipped with the application, sorted by key."""
    return sorted(
        (
            QuestionnaireDef.model_validate_json(path.read_text(encoding="utf-8"))
            for path in DEFINITIONS_DIR.glob("*.json")
        ),
        key=lambda d: d.key,
    )
