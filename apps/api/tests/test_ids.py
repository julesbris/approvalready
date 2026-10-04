import uuid

from app.db import base
from app.db.base import uuid7


def test_uuid7_version_and_variant() -> None:
    value = uuid7()
    assert value.version == 7
    assert value.variant == uuid.RFC_4122


def test_fallback_uuid7_is_time_ordered(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delattr(base.uuid, "uuid7", raising=False)
    first = uuid7()
    times = iter([2_000_000_000_000_000_000, 2_000_000_000_001_000_000])
    monkeypatch.setattr(base.time, "time_ns", lambda: next(times))
    a, b = uuid7(), uuid7()
    assert a.version == b.version == first.version == 7
    assert a < b
