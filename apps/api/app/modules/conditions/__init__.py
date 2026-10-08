"""Condition AST shared by questionnaire branching (``visible_when``) and, from Milestone 4,
regulatory rules. Data only: JSON validated by Pydantic and evaluated by a dispatch table of
pure functions. There is no ``eval`` and no expression language to parse.

Evaluation uses three-valued logic. A comparison on a fact that is missing yields
``UNKNOWN`` rather than ``FALSE``, and ``UNKNOWN`` propagates through ``all``/``any``/``not``,
so missing information is never silently treated as a "no".

``apps/web/src/lib/conditions.ts`` mirrors the evaluator for instant branching in the
browser. Both are run against ``tests/fixtures/condition_vectors.json``; the API remains
authoritative.
"""

from app.modules.conditions.ast import (
    MAX_DEPTH,
    MAX_NODES,
    All,
    AnyOf,
    Condition,
    Leaf,
    Not,
    Op,
    parse_condition,
    referenced_facts,
)
from app.modules.conditions.evaluator import Tri, evaluate

__all__ = [
    "MAX_DEPTH",
    "MAX_NODES",
    "All",
    "AnyOf",
    "Condition",
    "Leaf",
    "Not",
    "Op",
    "Tri",
    "evaluate",
    "parse_condition",
    "referenced_facts",
]
