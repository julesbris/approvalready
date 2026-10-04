"""Questionnaire definitions, answer validation and branching (pure, no database)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.questionnaires.definition import QuestionnaireDef, load_bundled
from app.modules.questionnaires.engine import (
    AnswerInvalid,
    evaluate_answers,
    normalise_answer,
    spec_from_definition,
)


def definition(*questions: dict[str, Any], sections: list[Any] | None = None) -> QuestionnaireDef:
    return QuestionnaireDef.model_validate(
        {
            "key": "test.q",
            "vertical": "PLANNING",
            "title": "Test",
            "sections": sections or [{"title": "S", "questions": list(questions)}],
        }
    )


BRANCHING = definition(
    {"key": "has_pool", "type": "BOOLEAN", "label": "Pool?", "required": True},
    {
        "key": "pool_cert",
        "type": "SELECT",
        "label": "Certificate?",
        "required": True,
        "options": [{"value": "yes", "label": "Yes"}, {"value": "no", "label": "No"}],
        "visible_when": {"fact": "has_pool", "op": "equals", "value": True},
    },
    {
        "key": "cert_number",
        "type": "TEXT",
        "label": "Number",
        "required": True,
        "visible_when": {"fact": "pool_cert", "op": "equals", "value": "yes"},
    },
    {"key": "notes", "type": "TEXTAREA", "label": "Notes"},
)


# --- Definitions -----------------------------------------------------------------------


def test_bundled_definitions_are_valid_and_cover_every_vertical() -> None:
    bundled = load_bundled()
    assert {d.vertical for d in bundled} == {
        "PLANNING",
        "VESSEL",
        "BUSINESS",
        "GRANT",
        "SELL",
        "RENT",
    }
    for d in bundled:
        spec = spec_from_definition(d)
        # An empty questionnaire shows the unconditional questions and nothing crashes.
        state = evaluate_answers(spec, {})
        assert state.visible
        assert set(state.missing_required) <= set(state.visible)


def test_content_hash_is_stable_and_sensitive() -> None:
    a = definition({"key": "x", "type": "TEXT", "label": "X"})
    b = definition({"key": "x", "type": "TEXT", "label": "X"})
    c = definition({"key": "x", "type": "TEXT", "label": "X changed"})
    assert a.content_hash() == b.content_hash() != c.content_hash()


@pytest.mark.parametrize(
    ("questions", "message"),
    [
        (
            [
                {
                    "key": "b",
                    "type": "TEXT",
                    "label": "B",
                    "visible_when": {"fact": "a", "op": "exists"},
                },
                {"key": "a", "type": "TEXT", "label": "A"},
            ],
            "not asked earlier",
        ),
        (
            [
                {
                    "key": "a",
                    "type": "TEXT",
                    "label": "A",
                    "visible_when": {"fact": "a", "op": "exists"},
                }
            ],
            "not asked earlier",
        ),
        (
            [
                {"key": "a", "type": "TEXT", "label": "A"},
                {"key": "a", "type": "TEXT", "label": "A"},
            ],
            "duplicate",
        ),
        (
            [
                {
                    "key": "a",
                    "type": "SELECT",
                    "label": "A",
                    "options": [{"value": "x", "label": "X"}],
                }
            ],
            "two options",
        ),
        (
            [
                {
                    "key": "a",
                    "type": "TEXT",
                    "label": "A",
                    "options": [{"value": "x", "label": "X"}, {"value": "y", "label": "Y"}],
                }
            ],
            "only SELECT",
        ),
        (
            [{"key": "a", "type": "BOOLEAN", "label": "A", "validation": {"max_length": 3}}],
            "does not support",
        ),
        ([{"key": "a", "type": "OBJECT", "label": "A"}], "validation.fields"),
        (
            [{"key": "a", "type": "TEXT", "label": "A", "validation": {"pattern": "("}}],
            "invalid pattern",
        ),
        (
            [{"key": "a", "type": "NUMBER", "label": "A", "validation": {"min": 5, "max": 1}}],
            "greater than",
        ),
        (
            [
                {"key": "a", "type": "TEXT", "label": "A"},
                {
                    "key": "b",
                    "type": "TEXT",
                    "label": "B",
                    "visible_when": {"fact": "a", "op": "greater_than", "value": 1},
                },
            ],
            "number or date",
        ),
        (
            [
                {
                    "key": "a",
                    "type": "SELECT",
                    "label": "A",
                    "options": [{"value": "x", "label": "X"}, {"value": "y", "label": "Y"}],
                },
                {
                    "key": "b",
                    "type": "TEXT",
                    "label": "B",
                    "visible_when": {"fact": "a", "op": "equals", "value": "z"},
                },
            ],
            "no option",
        ),
        (
            [
                {
                    "key": "a",
                    "type": "MULTISELECT",
                    "label": "A",
                    "options": [{"value": "x", "label": "X"}, {"value": "y", "label": "Y"}],
                },
                {
                    "key": "b",
                    "type": "TEXT",
                    "label": "B",
                    "visible_when": {"fact": "a", "op": "in", "value": ["x"]},
                },
            ],
            "use 'contains'",
        ),
        (
            [
                {"key": "a", "type": "BOOLEAN", "label": "A"},
                {
                    "key": "b",
                    "type": "TEXT",
                    "label": "B",
                    "visible_when": {"fact": "a", "op": "equals", "value": "yes"},
                },
            ],
            "true or false",
        ),
        (
            [
                {
                    "key": "a",
                    "type": "TEXT",
                    "label": "A",
                    "visible_when": {"fact": "x", "op": "nope"},
                }
            ],
            "visible_when",
        ),
    ],
)
def test_invalid_definitions_rejected(questions: list[dict[str, Any]], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        definition(*questions)


def test_structured_answers_expose_field_facts() -> None:
    d = definition(
        {"key": "site", "type": "ADDRESS", "label": "Site"},
        {
            "key": "qld_only",
            "type": "TEXT",
            "label": "Q",
            "visible_when": {"fact": "site.state", "op": "equals", "value": "QLD"},
        },
    )
    spec = spec_from_definition(d)
    address = {"line1": "1 Esplanade", "suburb": "Cairns City", "state": "QLD", "postcode": "4870"}
    assert "qld_only" in evaluate_answers(spec, {"site": address}).visible
    assert "qld_only" not in evaluate_answers(spec, {"site": {**address, "state": "NSW"}}).visible


# --- Branching -------------------------------------------------------------------------


def test_branching_reveals_and_hides_dependants() -> None:
    spec = spec_from_definition(BRANCHING)
    empty = evaluate_answers(spec, {})
    assert empty.visible == ("has_pool", "notes")
    assert empty.missing_required == ("has_pool",)

    yes = evaluate_answers(spec, {"has_pool": True})
    assert yes.visible == ("has_pool", "pool_cert", "notes")
    assert yes.missing_required == ("pool_cert",)

    chain = evaluate_answers(spec, {"has_pool": True, "pool_cert": "yes"})
    assert chain.missing_required == ("cert_number",)

    # Changing the first answer hides the whole chain, and its answers become prunable.
    no = evaluate_answers(spec, {"has_pool": False, "pool_cert": "yes", "cert_number": "PS-1"})
    assert no.visible == ("has_pool", "notes")
    assert no.hidden_answered == ("pool_cert", "cert_number")
    assert no.missing_required == ()
    assert no.facts == {"has_pool": False}


def test_unanswered_controlling_question_keeps_dependants_hidden() -> None:
    """Unknown is not true: a question gated on a missing answer stays hidden."""
    d = definition(
        {"key": "lots", "type": "NUMBER", "label": "Lots"},
        {
            "key": "big",
            "type": "TEXT",
            "label": "Big",
            "visible_when": {"not": {"fact": "lots", "op": "less_than", "value": 3}},
        },
    )
    spec = spec_from_definition(d)
    assert "big" not in evaluate_answers(spec, {}).visible
    assert "big" in evaluate_answers(spec, {"lots": 5}).visible
    assert "big" not in evaluate_answers(spec, {"lots": 2}).visible


def test_bundled_planning_branches() -> None:
    planning = next(d for d in load_bundled() if d.key == "planning.general")
    spec = spec_from_definition(planning)
    sub = evaluate_answers(spec, {"planning.development_type": "subdivision"})
    assert "planning.proposed_lots" in sub.missing_required
    assert "planning.secondary_dwelling_bedrooms" not in sub.visible
    granny = evaluate_answers(spec, {"planning.development_type": "secondary_dwelling"})
    assert {"planning.secondary_dwelling_bedrooms", "planning.storeys"} <= set(
        granny.missing_required
    )
    constraints = evaluate_answers(spec, {"planning.known_constraints": ["flooding"]})
    assert "planning.constraints_details" in constraints.visible


# --- Answer validation -----------------------------------------------------------------


def q(type_: str, **extra: Any) -> Any:
    spec = spec_from_definition(definition({"key": "x", "type": type_, "label": "X", **extra}))
    return spec.questions[0]


OPTIONS = [{"value": "a", "label": "A"}, {"value": "b", "label": "B"}, {"value": "c", "label": "C"}]


@pytest.mark.parametrize(
    ("question", "raw", "stored"),
    [
        (q("TEXT"), "  hello  ", "hello"),
        (q("TEXT"), "   ", None),
        (q("TEXT", validation={"pattern": "[0-9]{4}"}), "4870", "4870"),
        (q("TEXTAREA"), "line\nline", "line\nline"),
        (q("NUMBER"), 3, 3),
        (q("NUMBER"), "42", 42),
        (q("NUMBER"), 5.0, 5),
        (q("DECIMAL"), "600.50", "600.5"),
        (q("DECIMAL"), 12, "12"),
        (q("DECIMAL"), "1E+2", "100"),
        (q("DECIMAL"), "-0.0", "0"),
        (q("CURRENCY"), 125000, 125000),
        (q("BOOLEAN"), False, False),
        (q("SELECT", options=OPTIONS), "b", "b"),
        (q("MULTISELECT", options=OPTIONS), ["c", "a", "a"], ["a", "c"]),
        (q("MULTISELECT", options=OPTIONS), [], None),
        (q("DATE"), "2026-02-28", "2026-02-28"),
        (
            q("ADDRESS"),
            {
                "line1": " 1 Esplanade ",
                "line2": "",
                "suburb": "Cairns City",
                "state": "QLD",
                "postcode": "4870",
            },
            {"line1": "1 Esplanade", "suburb": "Cairns City", "state": "QLD", "postcode": "4870"},
        ),
        (
            q(
                "OBJECT",
                validation={
                    "fields": [
                        {"key": "name", "label": "Name", "type": "TEXT", "required": True},
                        {"key": "size", "label": "Size", "type": "DECIMAL"},
                        {"key": "on", "label": "On", "type": "DATE"},
                    ]
                },
            ),
            {"name": "Shed", "size": 12.5, "on": ""},
            {"name": "Shed", "size": "12.5"},
        ),
        (q("TEXT"), None, None),
    ],
)
def test_valid_answers_normalise(question: Any, raw: Any, stored: Any) -> None:
    assert normalise_answer(question, raw) == stored


@pytest.mark.parametrize(
    ("question", "raw", "message"),
    [
        (q("TEXT"), 12, "Enter text"),
        (q("TEXT"), "x" * 201, "200 characters"),
        (q("TEXT", validation={"min_length": 3}), "ab", "at least 3"),
        (
            q("TEXT", validation={"pattern": "[0-9]{4}", "pattern_message": "Four digits."}),
            "48701",
            "Four digits",
        ),
        (q("NUMBER"), True, "whole number"),
        (q("NUMBER"), 1.5, "whole number"),
        (q("NUMBER"), "1e3", "whole number"),
        (q("NUMBER"), 10**16, "whole number"),
        (q("NUMBER", validation={"min": 2}), 1, "2 or more"),
        (q("NUMBER", validation={"max": 10}), 11, "10 or less"),
        (q("DECIMAL"), "abc", "Enter a number"),
        (q("DECIMAL"), "NaN", "Enter a number"),
        (q("DECIMAL"), "Infinity", "Enter a number"),
        (q("DECIMAL"), True, "Enter a number"),
        (q("DECIMAL", validation={"max_decimal_places": 1}), "1.25", "1 decimal place"),
        (q("CURRENCY"), -5, "zero or more"),
        (q("CURRENCY"), 10.5, "whole number"),
        (q("BOOLEAN"), "yes", "yes or no"),
        (q("BOOLEAN"), 1, "yes or no"),
        (q("SELECT", options=OPTIONS), "z", "Choose one"),
        (q("SELECT", options=OPTIONS), ["a"], "Choose one"),
        (q("MULTISELECT", options=OPTIONS), "a", "Choose from"),
        (q("MULTISELECT", options=OPTIONS), ["a", "z"], "Choose from"),
        (q("MULTISELECT", options=OPTIONS, validation={"max_items": 1}), ["a", "b"], "at most 1"),
        (q("MULTISELECT", options=OPTIONS, validation={"min_items": 2}), ["a"], "at least 2"),
        (q("DATE"), "28/02/2026", "YYYY-MM-DD"),
        (q("DATE"), "2026-02-30", "real date"),
        (q("DATE", validation={"min_date": "2026-01-01"}), "2025-12-31", "on or after"),
        (q("DATE", validation={"max_date": "2026-01-01"}), "2026-01-02", "on or before"),
        (q("ADDRESS"), "1 Esplanade", "Enter the address"),
        (
            q("ADDRESS"),
            {"line1": "1 A St", "suburb": "X", "state": "QLD", "postcode": "487"},
            "postcode",
        ),
        (
            q("ADDRESS"),
            {"line1": "1 A St", "suburb": "X", "state": "Qld", "postcode": "4870"},
            "state",
        ),
        (
            q("ADDRESS"),
            {"line1": "", "suburb": "X", "state": "QLD", "postcode": "4870"},
            "street address",
        ),
        (
            q("ADDRESS"),
            {"line1": "1 A St", "suburb": "X", "state": "QLD", "postcode": "4870", "country": "AU"},
            "Enter the address",
        ),
        (
            q(
                "OBJECT",
                validation={
                    "fields": [{"key": "name", "label": "Name", "type": "TEXT", "required": True}]
                },
            ),
            {},
            "Enter name",
        ),
        (
            q("OBJECT", validation={"fields": [{"key": "n", "label": "Count", "type": "NUMBER"}]}),
            {"n": "many"},
            "Count: Enter a whole number",
        ),
        (
            q("OBJECT", validation={"fields": [{"key": "n", "label": "N", "type": "NUMBER"}]}),
            {"other": 1},
            "Complete the fields",
        ),
        (q("FILE"), ["00000000-0000-0000-0000-000000000000"], "not available yet"),
    ],
)
def test_invalid_answers_rejected(question: Any, raw: Any, message: str) -> None:
    with pytest.raises(AnswerInvalid, match=message):
        normalise_answer(question, raw)


def test_facts_are_typed() -> None:
    d = definition(
        {"key": "area", "type": "DECIMAL", "label": "Area"},
        {"key": "start", "type": "DATE", "label": "Start"},
        {"key": "cost", "type": "CURRENCY", "label": "Cost"},
    )
    state = evaluate_answers(
        spec_from_definition(d), {"area": "600.5", "start": "2026-03-01", "cost": 1500}
    )
    assert state.facts == {"area": Decimal("600.5"), "start": date(2026, 3, 1), "cost": 1500}
