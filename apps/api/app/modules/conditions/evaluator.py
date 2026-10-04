"""Three-valued evaluation of a condition against a dictionary of facts.

Facts are plain values keyed by fact path: ``str``, ``bool``, ``int``, ``Decimal``/``float``,
``datetime.date`` or ISO ``YYYY-MM-DD`` strings, and lists of those (multi-select answers).
A fact that is absent or ``None`` is *missing*.

Comparison semantics (mirrored in ``apps/web/src/lib/conditions.ts``):

* numbers compare numerically (``1 == 1.0``); booleans are never numbers;
* ordering (``greater_than`` …) works on two numbers or two dates, otherwise ``UNKNOWN``;
* ``equals`` on a list fact means "exactly that one value is chosen";
* ``contains`` means list membership, or substring for text;
* ``in``/``not_in`` test a single value against the condition's list;
* ``exists``/``missing`` are the only operators that are definite on a missing fact.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from app.modules.conditions.ast import All, AnyOf, Leaf, Not, Op


class Tri(StrEnum):
    TRUE = "TRUE"
    FALSE = "FALSE"
    UNKNOWN = "UNKNOWN"

    @staticmethod
    def of(value: bool) -> Tri:
        return Tri.TRUE if value else Tri.FALSE


_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, int | float | Decimal):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:  # nan/inf
        return None


def _date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and _DATE.match(value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _same(a: Any, b: Any) -> bool:
    na, nb = _number(a), _number(b)
    if na is not None or nb is not None:
        return na is not None and nb is not None and na == nb
    da, db = _date(a), _date(b)
    if da is not None and db is not None:
        return da == db
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    return isinstance(a, str) and isinstance(b, str) and a == b


def _equals(fact: Any, value: Any) -> Tri:
    if isinstance(fact, list):
        return Tri.of(len(fact) == 1 and _same(fact[0], value))
    return Tri.of(_same(fact, value))


def _order(fact: Any, value: Any, test: Callable[[int], bool]) -> Tri:
    na, nb = _number(fact), _number(value)
    if na is not None and nb is not None:
        return Tri.of(test((na > nb) - (na < nb)))
    da, db = _date(fact), _date(value)
    if da is not None and db is not None:
        return Tri.of(test((da > db) - (da < db)))
    return Tri.UNKNOWN


def _contains(fact: Any, value: Any) -> Tri:
    if isinstance(fact, list):
        return Tri.of(any(_same(item, value) for item in fact))
    if isinstance(fact, str) and isinstance(value, str):
        return Tri.of(value.casefold() in fact.casefold())
    return Tri.UNKNOWN


def _in(fact: Any, value: Any) -> Tri:
    if isinstance(fact, list) or not isinstance(value, list):
        return Tri.UNKNOWN
    return Tri.of(any(_same(fact, v) for v in value))


def _negate(result: Tri) -> Tri:
    if result is Tri.UNKNOWN:
        return Tri.UNKNOWN
    return Tri.FALSE if result is Tri.TRUE else Tri.TRUE


_OPERATORS: dict[Op, Callable[[Any, Any], Tri]] = {
    Op.EQUALS: _equals,
    Op.NOT_EQUALS: lambda f, v: _negate(_equals(f, v)),
    Op.GREATER_THAN: lambda f, v: _order(f, v, lambda c: c > 0),
    Op.LESS_THAN: lambda f, v: _order(f, v, lambda c: c < 0),
    Op.GREATER_EQUAL: lambda f, v: _order(f, v, lambda c: c >= 0),
    Op.LESS_EQUAL: lambda f, v: _order(f, v, lambda c: c <= 0),
    Op.CONTAINS: _contains,
    Op.NOT_CONTAINS: lambda f, v: _negate(_contains(f, v)),
    Op.IN: _in,
    Op.NOT_IN: lambda f, v: _negate(_in(f, v)),
}


def _missing(value: Any) -> bool:
    return value is None or (isinstance(value, list | str) and len(value) == 0)


def evaluate(node: All | AnyOf | Not | Leaf, facts: Mapping[str, Any]) -> Tri:
    if isinstance(node, All):
        results = [evaluate(child, facts) for child in node.all]
        if Tri.FALSE in results:
            return Tri.FALSE
        return Tri.UNKNOWN if Tri.UNKNOWN in results else Tri.TRUE
    if isinstance(node, AnyOf):
        results = [evaluate(child, facts) for child in node.any]
        if Tri.TRUE in results:
            return Tri.TRUE
        return Tri.UNKNOWN if Tri.UNKNOWN in results else Tri.FALSE
    if isinstance(node, Not):
        return _negate(evaluate(node.not_, facts))

    fact = facts.get(node.fact)
    if node.op is Op.EXISTS:
        return Tri.of(not _missing(fact))
    if node.op is Op.MISSING:
        return Tri.of(_missing(fact))
    if _missing(fact):
        return Tri.UNKNOWN
    return _OPERATORS[node.op](fact, node.value)
