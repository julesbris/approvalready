"""Answer validation, branching and completeness for one questionnaire version.

Pure functions over a compiled questionnaire (no database access), so the same logic serves
saving answers, submitting, and (from Milestone 4) turning answers into rule facts.

Branching: questions are considered in order. A question is visible when it has no
``visible_when`` or its condition evaluates to ``TRUE`` against the answers to *visible*
earlier questions. An answer to a hidden question is not a fact; it is pruned when answers
are saved, so a changed "yes" to "no" never leaves stale dependent answers behind.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.modules.conditions import Tri, evaluate, parse_condition
from app.modules.conditions.ast import All, AnyOf, Leaf, Not
from app.modules.entities.models import AustralianState
from app.modules.questionnaires.definition import (
    DEFAULT_MAX_LENGTH,
    FieldDef,
    QuestionnaireDef,
    ValidationDef,
)
from app.modules.questionnaires.models import QuestionType

QT = QuestionType
DEFAULT_DECIMAL_PLACES = 4
MAX_INT = 10**15  # comfortably inside JavaScript's safe integer range


class AnswerInvalid(ValueError):
    """The answer does not fit the question. ``str(exc)`` is safe to show to the user."""


@dataclass(frozen=True)
class OptionSpec:
    value: str
    label: str


@dataclass(frozen=True)
class QuestionSpec:
    id: Any  # question_version.id
    key: str
    type: QuestionType
    section: str
    label: str
    help_text: str | None
    required: bool
    options: tuple[OptionSpec, ...]
    validation: ValidationDef
    visible_when: All | AnyOf | Not | Leaf | None

    @property
    def option_values(self) -> tuple[str, ...]:
        return tuple(o.value for o in self.options)


@dataclass(frozen=True)
class QuestionnaireSpec:
    version_id: Any
    questionnaire_key: str
    vertical: str
    version: int
    title: str
    description: str | None
    questions: tuple[QuestionSpec, ...]
    by_key: dict[str, QuestionSpec] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "by_key", {q.key: q for q in self.questions})

    def sections(self) -> list[tuple[str, list[QuestionSpec]]]:
        grouped: list[tuple[str, list[QuestionSpec]]] = []
        for q in self.questions:
            if not grouped or grouped[-1][0] != q.section:
                grouped.append((q.section, []))
            grouped[-1][1].append(q)
        return grouped


def compile_question(
    *,
    id: Any,
    key: str,
    type: str,
    section: str,
    label: str,
    help_text: str | None,
    required: bool,
    options: list[tuple[str, str]],
    validation: Mapping[str, Any],
    visible_when: Mapping[str, Any] | None,
) -> QuestionSpec:
    return QuestionSpec(
        id=id,
        key=key,
        type=QuestionType(type),
        section=section,
        label=label,
        help_text=help_text,
        required=required,
        options=tuple(OptionSpec(v, lbl) for v, lbl in options),
        validation=ValidationDef.model_validate(validation),
        visible_when=parse_condition(visible_when) if visible_when else None,
    )


def spec_from_definition(definition: QuestionnaireDef, version: int = 1) -> QuestionnaireSpec:
    """Compile a definition directly (question ids are the keys). For previews and tests;
    served questionnaires are compiled from their stored, immutable version."""
    return QuestionnaireSpec(
        version_id=None,
        questionnaire_key=definition.key,
        vertical=definition.vertical,
        version=version,
        title=definition.title,
        description=definition.description,
        questions=tuple(
            compile_question(
                id=q.key,
                key=q.key,
                type=q.type,
                section=section.title,
                label=q.label,
                help_text=q.help_text,
                required=q.required,
                options=[(o.value, o.label) for o in q.options],
                validation=q.validation.model_dump(exclude_none=True),
                visible_when=q.visible_when,
            )
            for section in definition.sections
            for q in section.questions
        ),
    )


# --- Normalising answers ---------------------------------------------------------------


def _text(value: Any, v: ValidationDef, qtype: QuestionType) -> str | None:
    if not isinstance(value, str):
        raise AnswerInvalid("Enter text.")
    value = value.strip()
    if value == "":
        return None
    max_length = v.max_length or DEFAULT_MAX_LENGTH.get(qtype, 200)
    if len(value) > max_length:
        raise AnswerInvalid(f"Keep this to {max_length} characters or fewer.")
    if v.min_length is not None and len(value) < v.min_length:
        raise AnswerInvalid(f"Enter at least {v.min_length} characters.")
    if v.pattern is not None and not re.fullmatch(v.pattern, value):
        raise AnswerInvalid(v.pattern_message or "Check the format of this answer.")
    return str(value)


def _range(number: Decimal, v: ValidationDef) -> None:
    if v.min is not None and number < v.min:
        raise AnswerInvalid(f"Enter {v.min:f} or more.")
    if v.max is not None and number > v.max:
        raise AnswerInvalid(f"Enter {v.max:f} or less.")


def _integer(value: Any, v: ValidationDef) -> int:
    if isinstance(value, bool):
        raise AnswerInvalid("Enter a whole number.")
    if isinstance(value, str) and re.fullmatch(r"-?\d{1,16}", value.strip()):
        value = int(value.strip())
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if not isinstance(value, int) or abs(value) > MAX_INT:
        raise AnswerInvalid("Enter a whole number.")
    _range(Decimal(value), v)
    return value


def _decimal(value: Any, v: ValidationDef) -> str:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise AnswerInvalid("Enter a number.")
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation:
        raise AnswerInvalid("Enter a number.") from None
    if not number.is_finite() or abs(number) > MAX_INT:
        raise AnswerInvalid("Enter a number.")
    places = v.max_decimal_places if v.max_decimal_places is not None else DEFAULT_DECIMAL_PLACES
    exponent = number.as_tuple().exponent
    if isinstance(exponent, int) and -exponent > places:
        raise AnswerInvalid(f"Use at most {places} decimal places.")
    _range(number, v)
    normalised = format(number.normalize(), "f")
    return "0" if normalised in {"-0", ""} else normalised


def _date_value(value: Any, v: ValidationDef) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise AnswerInvalid("Enter a date as YYYY-MM-DD.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise AnswerInvalid("Enter a real date.") from None
    if v.min_date is not None and parsed < v.min_date:
        raise AnswerInvalid(f"Enter a date on or after {v.min_date.isoformat()}.")
    if v.max_date is not None and parsed > v.max_date:
        raise AnswerInvalid(f"Enter a date on or before {v.max_date.isoformat()}.")
    return value


def _address(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise AnswerInvalid("Enter the address.")
    unknown = set(value) - {"line1", "line2", "suburb", "state", "postcode"}
    if unknown:
        raise AnswerInvalid("Enter the address.")
    out: dict[str, str] = {}
    for name, required, limit in (
        ("line1", True, 200),
        ("line2", False, 200),
        ("suburb", True, 100),
    ):
        raw = value.get(name)
        text = raw.strip() if isinstance(raw, str) else ""
        if raw is not None and not isinstance(raw, str):
            raise AnswerInvalid("Enter the address.")
        if required and not text:
            raise AnswerInvalid("Enter the street address and suburb.")
        if len(text) > limit:
            raise AnswerInvalid("That address line is too long.")
        if text:
            out[name] = text
    state = value.get("state")
    if state not in set(AustralianState):
        raise AnswerInvalid("Choose a state or territory.")
    postcode = value.get("postcode")
    if not isinstance(postcode, str) or not re.fullmatch(r"\d{4}", postcode.strip()):
        raise AnswerInvalid("Enter a 4-digit postcode.")
    out["state"] = str(state)
    out["postcode"] = postcode.strip()
    return out


def _object(value: Any, fields: list[FieldDef]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AnswerInvalid("Complete the fields.")
    known = {f.key: f for f in fields}
    if set(value) - set(known):
        raise AnswerInvalid("Complete the fields.")
    out: dict[str, Any] = {}
    plain = ValidationDef()
    for f in fields:
        raw = value.get(f.key)
        if raw is None or raw == "":
            if f.required:
                raise AnswerInvalid(f"Enter {f.label.lower()}.")
            continue
        try:
            if f.type == "TEXT":
                normalised: Any = _text(raw, plain, QT.TEXT)
            elif f.type == "NUMBER":
                normalised = _integer(raw, plain)
            elif f.type == "DECIMAL":
                normalised = _decimal(raw, plain)
            elif f.type == "BOOLEAN":
                if not isinstance(raw, bool):
                    raise AnswerInvalid("Choose yes or no.")
                normalised = raw
            else:
                normalised = _date_value(raw, plain)
        except AnswerInvalid as exc:
            raise AnswerInvalid(f"{f.label}: {exc}") from None
        if normalised is not None:
            out[f.key] = normalised
    return out


DEFAULT_MAX_FILES = 5


def _file_ids(value: Any, v: ValidationDef) -> list[str] | None:
    """Uploaded document ids, in order, without duplicates. Whether each one exists in the
    project and passed its virus check is the service's job (it needs the database)."""
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise AnswerInvalid("Upload the files again.")
    ids: list[str] = []
    for raw in value:
        try:
            normalised = str(uuid.UUID(raw))
        except ValueError:
            raise AnswerInvalid("Upload the files again.") from None
        if normalised not in ids:
            ids.append(normalised)
    if not ids:
        return None
    limit = v.max_files or DEFAULT_MAX_FILES
    if len(ids) > limit:
        raise AnswerInvalid(f"Attach at most {limit} file{'' if limit == 1 else 's'}.")
    return ids


def normalise_answer(q: QuestionSpec, value: Any) -> Any:
    """Validate ``value`` for ``q`` and return its stored JSON form. ``None`` means "clear"."""
    if value is None:
        return None
    v = q.validation
    match q.type:
        case QT.TEXT | QT.TEXTAREA:
            return _text(value, v, q.type)
        case QT.NUMBER:
            return _integer(value, v)
        case QT.CURRENCY:
            cents = _integer(value, v)
            if cents < 0 and (v.min is None or v.min >= 0):
                raise AnswerInvalid("Enter an amount of zero or more.")
            return cents
        case QT.DECIMAL:
            return _decimal(value, v)
        case QT.BOOLEAN:
            if not isinstance(value, bool):
                raise AnswerInvalid("Choose yes or no.")
            return value
        case QT.SELECT:
            if not isinstance(value, str) or value not in q.option_values:
                raise AnswerInvalid("Choose one of the options.")
            return value
        case QT.MULTISELECT:
            if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
                raise AnswerInvalid("Choose from the options.")
            chosen = set(value)
            if not chosen <= set(q.option_values):
                raise AnswerInvalid("Choose from the options.")
            if not chosen:
                return None
            if v.min_items is not None and len(chosen) < v.min_items:
                raise AnswerInvalid(f"Choose at least {v.min_items}.")
            if v.max_items is not None and len(chosen) > v.max_items:
                raise AnswerInvalid(f"Choose at most {v.max_items}.")
            return [o for o in q.option_values if o in chosen]
        case QT.DATE:
            return _date_value(value, v)
        case QT.ADDRESS:
            return _address(value)
        case QT.OBJECT:
            return _object(value, v.fields or []) or None
        case QT.FILE:
            return _file_ids(value, v)
    raise AnswerInvalid("Unsupported question.")  # pragma: no cover


# --- Facts and branching ---------------------------------------------------------------


def to_facts(q: QuestionSpec, stored: Any) -> dict[str, Any]:
    """Typed facts provided by one stored answer (structured answers also expose fields)."""
    if stored is None:
        return {}
    if q.type == QT.DECIMAL:
        return {q.key: Decimal(stored)}
    if q.type == QT.DATE:
        return {q.key: date.fromisoformat(stored)}
    if q.type in {QT.ADDRESS, QT.OBJECT} and isinstance(stored, dict):
        facts: dict[str, Any] = {q.key: stored}
        decimals = {f.key for f in q.validation.fields or [] if f.type == "DECIMAL"}
        dates = {f.key for f in q.validation.fields or [] if f.type == "DATE"}
        for name, value in stored.items():
            if name in decimals:
                value = Decimal(value)
            elif name in dates:
                value = date.fromisoformat(value)
            facts[f"{q.key}.{name}"] = value
        return facts
    return {q.key: stored}


@dataclass(frozen=True)
class AnswerState:
    visible: tuple[str, ...]
    facts: dict[str, Any]
    answered: tuple[str, ...]  # visible and answered
    hidden_answered: tuple[str, ...]  # answered but hidden: to prune
    missing_required: tuple[str, ...]


def evaluate_answers(spec: QuestionnaireSpec, answers: Mapping[str, Any]) -> AnswerState:
    facts: dict[str, Any] = {}
    visible: list[str] = []
    answered: list[str] = []
    hidden_answered: list[str] = []
    missing: list[str] = []
    for q in spec.questions:
        shown = q.visible_when is None or evaluate(q.visible_when, facts) is Tri.TRUE
        has_answer = answers.get(q.key) is not None
        if not shown:
            if has_answer:
                hidden_answered.append(q.key)
            continue
        visible.append(q.key)
        if has_answer:
            answered.append(q.key)
            facts.update(to_facts(q, answers[q.key]))
        elif q.required:
            missing.append(q.key)
    return AnswerState(
        visible=tuple(visible),
        facts=facts,
        answered=tuple(answered),
        hidden_answered=tuple(hidden_answered),
        missing_required=tuple(missing),
    )
