"""RemoteSafe risk engine, policy and time zones (no database).

All journeys here are SIMULATED test data: places are real towns, but surfaces, coverage,
crossings and closures are invented for the test and are not road information.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.core.errors import ApiError
from app.modules.remotesafe import engine
from app.modules.remotesafe.policy import build_policy, library
from app.modules.remotesafe.timezones import label, to_utc

BNE = ZoneInfo("Australia/Brisbane")


def at(hour: int, minute: int = 0, day: int = 24, zone: ZoneInfo = BNE) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=zone).astimezone(UTC)


def cooktown_coen(**overrides: object) -> engine.JourneyIn:
    """SIMULATED Cooktown to Coen trip via Lakeland and Laura: remote, mostly unsealed."""
    legs = (
        engine.LegIn(
            1,
            "Cooktown",
            "Lakeland",
            at(6),
            at(7, 30),
            "Australia/Brisbane",
            80,
            "SEALED",
            "PATCHY",
            1,
            "NONE_KNOWN",
        ),
        engine.LegIn(
            2,
            "Lakeland",
            "Laura",
            at(7, 45),
            at(8, 45),
            "Australia/Brisbane",
            60,
            "SEALED",
            "NONE",
            2,
            "NONE_KNOWN",
        ),
        engine.LegIn(
            3,
            "Laura",
            "Coen",
            at(9),
            at(13),
            "Australia/Brisbane",
            245,
            "UNSEALED",
            "NONE",
            6,
            "NONE_KNOWN",
        ),
    )
    values: dict[str, object] = {
        "departs_at": at(6),
        "arrives_at": at(13),
        "timezone": "Australia/Brisbane",
        "legs": legs,
        "occupants": 1,
        "remoteness": "VERY_REMOTE",
        "comms_mobile": True,
        "has_monitor": True,
        "emergency_contacts": 2,
        "checkins": (at(7, 30), at(8, 45), at(11)),
        "weather_checked_at": at(5),
        "weather_source": "Bureau of Meteorology warnings page",
        "vehicle_known": True,
        "fuel_range_km": 700.0,
    }
    values.update(overrides)
    return engine.JourneyIn(**values)  # type: ignore[arg-type]


def keys(result: engine.Assessment) -> set[str]:
    return {f.key for f in result.findings}


def test_cooktown_to_coen_without_satellite_is_critical() -> None:
    result = engine.assess(cooktown_coen(), build_policy())
    assert result.outcome == "CRITICAL"
    assert [s.key for s in result.stops] == ["emergency_communications"]
    assert {
        "communications",
        "remote_work",
        "working_alone",
        "unsealed_roads",
        "corrugations",
        "flood_crossings",
        "dangerous_wildlife",
        "emergency_response",
        "extreme_heat",  # November is a hot month in the default policy assumption
    } <= keys(result)
    assert "satellite_device" in result.mandatory_controls
    # Every finding cites evidence and where it came from.
    for f in result.findings:
        assert f.evidence and all(e["source"] for e in f.evidence)


def test_cooktown_to_coen_with_satellite_messenger_is_high_not_critical() -> None:
    result = engine.assess(cooktown_coen(comms_sat_messenger=True), build_policy())
    assert result.stops == []
    assert result.outcome == "HIGH"
    worst = result.findings[0]
    assert worst.residual_rating == "HIGH"
    assert worst.initial_score == worst.likelihood * worst.consequence


def test_confirmed_closure_is_a_stop_condition_with_its_source() -> None:
    j = cooktown_coen(comms_sat_phone=True)
    closed = engine.LegIn(
        3,
        "Laura",
        "Coen",
        at(9),
        at(13),
        "Australia/Brisbane",
        245,
        "UNSEALED",
        "NONE",
        6,
        "CONFIRMED_CLOSED",
        "QLDTraffic (SIMULATED)",
        at(5),
    )
    result = engine.assess(
        engine.JourneyIn(**{**j.__dict__, "legs": (*j.legs[:2], closed)}), build_policy()
    )
    assert result.outcome == "CRITICAL"
    stop = next(s for s in result.stops if s.key == "route_closure")
    assert "QLDTraffic (SIMULATED)" in stop.evidence[0]["source"]
    assert stop.evidence[0]["observed_at"] is not None


def test_missing_emergency_arrangements_stop() -> None:
    result = engine.assess(
        cooktown_coen(comms_sat_phone=True, has_monitor=False, checkins=()), build_policy()
    )
    stop = next(s for s in result.stops if s.key == "emergency_arrangements")
    assert {e["fact"] for e in stop.evidence} == {"Journey monitor", "Planned check-ins"}
    assert "delayed_rescue" in keys(result)


def test_short_sealed_town_trip_is_low() -> None:
    leg = engine.LegIn(
        1,
        "Cairns",
        "Gordonvale",
        at(9),
        at(9, 40),
        "Australia/Brisbane",
        25,
        "SEALED",
        "GOOD",
        0,
        "NONE_KNOWN",
    )
    j = engine.JourneyIn(
        departs_at=at(9),
        arrives_at=at(9, 40),
        timezone="Australia/Brisbane",
        legs=(leg,),
        occupants=2,
        remoteness="NOT_REMOTE",
        has_monitor=True,
        emergency_contacts=1,
        checkins=(at(9, 40),),
        weather_checked_at=at(8),
        fuel_range_km=600,
    )
    result = engine.assess(j, build_policy())
    assert result.stops == []
    assert result.findings == []
    assert result.outcome == "LOW"


def test_night_driving_uses_the_legs_own_time_zone() -> None:
    """19:00 to 21:00 in Perth is night there, though it is already late in Brisbane."""
    per = ZoneInfo("Australia/Perth")
    leg = engine.LegIn(
        1,
        "Perth",
        "Northam",
        at(19, zone=per),
        at(21, zone=per),
        "Australia/Perth",
        100,
        "SEALED",
        "GOOD",
        0,
        "NONE_KNOWN",
    )
    j = engine.JourneyIn(
        departs_at=leg.departs_at,
        arrives_at=leg.arrives_at,
        timezone="Australia/Perth",
        legs=(leg,),
    )
    total, night, _ = engine.driving_profile(j, build_policy())
    assert total == 2.0
    assert night == 2.0
    # The same wall-clock hours in the morning are not night.
    morning = engine.LegIn(
        1,
        "Perth",
        "Northam",
        at(9, zone=per),
        at(11, zone=per),
        "Australia/Perth",
        100,
    )
    j2 = engine.JourneyIn(
        departs_at=morning.departs_at,
        arrives_at=morning.arrives_at,
        timezone="Australia/Perth",
        legs=(morning,),
    )
    assert engine.driving_profile(j2, build_policy())[1] == 0.0


def test_daylight_saving_difference_between_queensland_and_nsw() -> None:
    # 24 November 2026: Sydney is on daylight saving (UTC+11), Brisbane is not (UTC+10).
    brisbane = to_utc(datetime(2026, 11, 24, 8, 0), "Australia/Brisbane")
    sydney = to_utc(datetime(2026, 11, 24, 8, 0), "Australia/Sydney")
    assert brisbane - sydney == timedelta(hours=1)
    assert label(brisbane, "Australia/Brisbane").endswith("AEST")
    assert label(sydney, "Australia/Sydney").endswith("AEDT")
    assert label(brisbane, "Australia/Broken_Hill").endswith("ACDT")


def test_nonexistent_local_time_is_refused() -> None:
    # Clocks in Sydney go from 02:00 to 03:00 on 4 October 2026.
    with pytest.raises(ApiError) as e:
        to_utc(datetime(2026, 10, 4, 2, 30), "Australia/Sydney")
    assert e.value.code == "nonexistent_local_time"
    # Queensland has no daylight saving: the same wall time exists.
    to_utc(datetime(2026, 10, 4, 2, 30), "Australia/Brisbane")


def test_non_australian_zone_refused() -> None:
    with pytest.raises(ApiError):
        to_utc(datetime(2026, 1, 1, 8), "Europe/London")


def test_checkin_gap_over_policy_triggers_delayed_rescue() -> None:
    result = engine.assess(cooktown_coen(comms_sat_phone=True, checkins=(at(12),)), build_policy())
    assert result.facts["longest_checkin_gap_minutes"] == 360
    assert "delayed_rescue" in keys(result)


def test_fuel_range_shorter_than_leg() -> None:
    result = engine.assess(cooktown_coen(comms_sat_phone=True, fuel_range_km=250.0), build_policy())
    supplies = next(f for f in result.findings if f.key == "supplies")
    assert any("Vehicle fuel range" in e["fact"] for e in supplies.evidence)


# --- Policy ----------------------------------------------------------------------------


def test_policy_overrides_change_ratings() -> None:
    strict = build_policy({"hazards": {"working_alone": {"likelihood": 5, "consequence": 5}}})
    result = engine.assess(cooktown_coen(comms_sat_phone=True), strict)
    alone = next(f for f in result.findings if f.key == "working_alone")
    assert alone.initial_rating == "CRITICAL"
    assert alone.residual_score == 2 * 5


def test_disabled_hazard_does_not_remove_stop_conditions() -> None:
    policy = build_policy({"hazards": {"communications": {"enabled": False}}})
    result = engine.assess(cooktown_coen(), policy)
    assert "communications" not in keys(result)
    assert [s.key for s in result.stops] == ["emergency_communications"]
    assert result.outcome == "CRITICAL"


def test_extra_mandatory_controls_only_add() -> None:
    policy = build_policy({"extra_mandatory_controls": ["comms_tested"]})
    assert policy.controls["comms_tested"].mandatory
    assert policy.controls["vehicle_prestart"].mandatory


@pytest.mark.parametrize(
    "overrides",
    [
        {"rating_bands": {"moderate": 10, "high": 5, "critical": 17}},
        {"hazards": {"fatigue": {"likelihood": 6}}},
        {"hazards": {"fatigue": {"likelihood": 2, "residual_likelihood": 3}}},
        {"hazards": {"fatigue": {"controls": []}}},
        {"hazards": {"made_up": {"likelihood": 2}}},
        {"assumptions": {"max_checkin_gap_minutes": 5}},
        {"assumptions": {"night_start": "late"}},
        {"extra_mandatory_controls": ["teleporter"]},
        {"high_risk_approver_roles": ["WORKER"]},
        {"stop_conditions": {"emergency_communications": False}},
    ],
)
def test_invalid_policy_refused(overrides: dict[str, object]) -> None:
    with pytest.raises(ApiError) as e:
        build_policy(overrides)
    assert e.value.code == "invalid_policy"


def test_library_is_consistent() -> None:
    data = library()
    controls = {c["key"] for c in data["controls"]}
    for h in data["hazards"]:
        assert set(h["controls"]) <= controls, h["key"]
        assert h["residual_likelihood"] <= h["likelihood"]
    assert len({h["key"] for h in data["hazards"]}) == len(data["hazards"])
