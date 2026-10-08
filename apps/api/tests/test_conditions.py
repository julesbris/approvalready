"""Condition AST: parsing limits and the evaluator, against vectors shared with the web app."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.conditions import (
    MAX_DEPTH,
    Tri,
    evaluate,
    missing_facts,
    parse_condition,
    trace,
)

VECTORS = json.loads(
    (Path(__file__).parents[3] / "tests" / "fixtures" / "condition_vectors.json").read_text()
)


@pytest.mark.parametrize("case", VECTORS, ids=[c["name"] for c in VECTORS])
def test_shared_vectors(case: dict[str, Any]) -> None:
    assert evaluate(parse_condition(case["condition"]), case["facts"]) == Tri(case["expected"])


@pytest.mark.parametrize("case", VECTORS, ids=[c["name"] for c in VECTORS])
def test_trace_agrees_with_evaluate(case: dict[str, Any]) -> None:
    node = parse_condition(case["condition"])
    traced = trace(node, case["facts"])
    assert traced["result"] == evaluate(node, case["facts"])
    json.dumps(traced)  # stored as JSONB with the finding


def test_trace_records_each_leaf_and_missing_facts() -> None:
    node = parse_condition(
        {
            "all": [
                {"fact": "site.area_m2", "op": "greater_equal", "value": 600},
                {"not": {"fact": "site.heritage", "op": "equals", "value": True}},
                {"any": [{"fact": "a", "op": "exists"}, {"fact": "b", "op": "equals", "value": 1}]},
            ]
        }
    )
    traced = trace(node, {"site.area_m2": Decimal("812.5"), "a": None})
    assert traced["result"] == "UNKNOWN"
    area, heritage, either = traced["children"]
    assert area == {
        "kind": "leaf",
        "fact": "site.area_m2",
        "op": "greater_equal",
        "value": 600,
        "actual": "812.5",
        "missing": False,
        "result": "TRUE",
    }
    assert heritage["kind"] == "not" and heritage["result"] == "UNKNOWN"
    assert heritage["children"][0]["missing"] is True
    # ``exists`` on a missing fact is definite (FALSE), so only ``b`` and the heritage fact
    # are information the customer could still provide.
    assert either["children"][0]["result"] == "FALSE"
    assert missing_facts(traced) == ["site.heritage", "b"]


def test_typed_facts_from_answers() -> None:
    """The API evaluates typed facts (Decimal, date) the same way as their JSON forms."""
    assert (
        evaluate(
            parse_condition({"fact": "n", "op": "greater_than", "value": 0.1}),
            {"n": Decimal("0.2")},
        )
        is Tri.TRUE
    )
    assert (
        evaluate(
            parse_condition({"fact": "d", "op": "less_than", "value": "2026-01-01"}),
            {"d": date(2025, 12, 31)},
        )
        is Tri.TRUE
    )


@pytest.mark.parametrize(
    "document",
    [
        {"fact": "a", "op": "in", "value": "x"},  # list operator needs a list
        {"fact": "a", "op": "in", "value": []},
        {"fact": "a", "op": "equals"},  # needs a value
        {"fact": "a", "op": "equals", "value": ["x"]},
        {"fact": "a", "op": "exists", "value": 1},  # takes none
        {"fact": "a", "op": "greater_than", "value": True},
        {"fact": "a", "op": "matches", "value": "x"},  # unknown operator
        {"fact": "A b", "op": "exists"},  # bad fact path
        {"fact": "a", "op": "exists", "extra": 1},
        {"all": []},
        {"all": [{"fact": "a", "op": "exists"}], "any": [{"fact": "a", "op": "exists"}]},
        {"eval": "__import__('os')"},
        "a == 1",
    ],
)
def test_invalid_conditions_rejected(document: object) -> None:
    with pytest.raises((ValidationError, ValueError)):
        parse_condition(document)


def test_depth_and_size_limits() -> None:
    node: dict[str, Any] = {"fact": "a", "op": "exists"}
    for _ in range(MAX_DEPTH - 1):
        node = {"not": node}
    parse_condition(node)
    with pytest.raises(ValueError, match="deeper"):
        parse_condition({"not": node})

    wide = {"all": [{"any": [{"fact": "a", "op": "exists"}] * 40}] * 3}  # > MAX_NODES
    with pytest.raises(ValueError, match="nodes"):
        parse_condition(wide)
