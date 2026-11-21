"""Australian time zones for journey times.

Times are stored in UTC. A worker enters local wall-clock times, read in the time zone of
the place they apply to (a leg's own zone, else the journey's), so a Cooktown departure is
Queensland time all year while a Broken Hill arrival follows South Australian daylight
saving. A wall time that doesn't exist (the hour skipped when daylight saving starts) is
refused rather than guessed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.core.errors import ApiError

AUSTRALIAN_ZONES: dict[str, str] = {
    "Australia/Brisbane": "Queensland",
    "Australia/Lindeman": "Queensland (Whitsundays)",
    "Australia/Sydney": "New South Wales and ACT",
    "Australia/Broken_Hill": "Broken Hill (NSW, South Australian time)",
    "Australia/Lord_Howe": "Lord Howe Island",
    "Australia/Melbourne": "Victoria",
    "Australia/Hobart": "Tasmania",
    "Australia/Adelaide": "South Australia",
    "Australia/Darwin": "Northern Territory",
    "Australia/Perth": "Western Australia",
    "Australia/Eucla": "Eucla (WA, central western time)",
}

DEFAULT_ZONE = "Australia/Brisbane"


def check_zone(name: str) -> str:
    if name not in AUSTRALIAN_ZONES:
        raise ApiError(422, "invalid_timezone", f"{name} is not an Australian time zone.")
    return name


def to_utc(value: datetime, zone: str, what: str = "Time") -> datetime:
    """A wall time in ``zone`` (or an aware time, converted as is) as UTC."""
    if value.tzinfo is not None:
        return value.astimezone(UTC)
    tz = ZoneInfo(check_zone(zone))
    local = value.replace(tzinfo=tz)
    # Round-trip: a wall time skipped by a daylight-saving change comes back different.
    back = local.astimezone(UTC).astimezone(tz).replace(tzinfo=None)
    if back != value:
        raise ApiError(
            422,
            "nonexistent_local_time",
            f"{what} {value:%d/%m/%Y %H:%M} doesn't exist in {AUSTRALIAN_ZONES[zone]}: "
            "the clocks skip that hour for daylight saving.",
        )
    return local.astimezone(UTC)


def local(value: datetime, zone: str) -> datetime:
    return value.astimezone(ZoneInfo(check_zone(zone)))


def label(value: datetime | None, zone: str) -> str:
    """``Sat 21 Nov 2026, 07:00 AEST`` style, for reports."""
    if value is None:
        return "Not set"
    t = local(value, zone)
    return f"{t:%a %d %b %Y, %H:%M} {t.tzname()}"
