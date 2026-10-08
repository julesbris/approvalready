"""Condition syntax tree.

JSON forms (exactly one key per node)::

    {"all": [<condition>, ...]}
    {"any": [<condition>, ...]}
    {"not": <condition>}
    {"fact": "property.lot_size_m2", "op": "greater_equal", "value": 600}

Size limits keep evaluation cheap and stop pathological documents.
"""

from __future__ import annotations

from collections.abc import Iterator
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

MAX_DEPTH = 8
MAX_NODES = 100
FACT_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$"

Scalar = str | int | float | bool


class Op(StrEnum):
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"
    GREATER_EQUAL = "greater_equal"
    LESS_EQUAL = "less_equal"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    IN = "in"
    NOT_IN = "not_in"
    EXISTS = "exists"
    MISSING = "missing"


UNARY_OPS = frozenset({Op.EXISTS, Op.MISSING})
LIST_OPS = frozenset({Op.IN, Op.NOT_IN})
ORDER_OPS = frozenset({Op.GREATER_THAN, Op.LESS_THAN, Op.GREATER_EQUAL, Op.LESS_EQUAL})


class _Node(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class Leaf(_Node):
    fact: str = Field(pattern=FACT_PATTERN, max_length=120)
    op: Op
    value: Scalar | list[Scalar] | None = None

    @model_validator(mode="after")
    def _check_value(self) -> Leaf:
        if self.op in UNARY_OPS:
            if self.value is not None:
                raise ValueError(f"'{self.op}' takes no value")
        elif self.op in LIST_OPS:
            if not isinstance(self.value, list) or not self.value:
                raise ValueError(f"'{self.op}' needs a non-empty list value")
            if len(self.value) > 50:
                raise ValueError("list values are limited to 50 items")
        elif self.value is None or isinstance(self.value, list):
            raise ValueError(f"'{self.op}' needs a single value")
        if self.op in ORDER_OPS and isinstance(self.value, bool):
            raise ValueError(f"'{self.op}' cannot compare booleans")
        return self


class All(_Node):
    all: list[Condition] = Field(min_length=1, max_length=50)


class AnyOf(_Node):
    any: list[Condition] = Field(min_length=1, max_length=50)


class Not(_Node):
    not_: Condition = Field(alias="not")


Condition = Annotated[All | AnyOf | Not | Leaf, Field(union_mode="left_to_right")]

All.model_rebuild()
AnyOf.model_rebuild()
Not.model_rebuild()

_ADAPTER: TypeAdapter[All | AnyOf | Not | Leaf] = TypeAdapter(Condition)


def children(node: All | AnyOf | Not | Leaf) -> list[All | AnyOf | Not | Leaf]:
    if isinstance(node, All):
        return list(node.all)
    if isinstance(node, AnyOf):
        return list(node.any)
    if isinstance(node, Not):
        return [node.not_]
    return []


def _walk(node: All | AnyOf | Not | Leaf, depth: int = 1) -> Iterator[tuple[Any, int]]:
    yield node, depth
    for child in children(node):
        yield from _walk(child, depth + 1)


def parse_condition(data: object) -> All | AnyOf | Not | Leaf:
    """Validate JSON into a condition, enforcing depth and size limits."""
    node = _ADAPTER.validate_python(data)
    for count, (_, depth) in enumerate(_walk(node), start=1):
        if depth > MAX_DEPTH:
            raise ValueError(f"condition nests deeper than {MAX_DEPTH} levels")
        if count > MAX_NODES:
            raise ValueError(f"condition has more than {MAX_NODES} nodes")
    return node


def dump_condition(node: All | AnyOf | Not | Leaf) -> dict[str, Any]:
    return node.model_dump(mode="json", by_alias=True, exclude_none=True)


def referenced_facts(node: All | AnyOf | Not | Leaf) -> list[Leaf]:
    return [n for n, _ in _walk(node) if isinstance(n, Leaf)]
