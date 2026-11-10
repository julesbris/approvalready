"""Neighbourhood scores out of 10, worked out from distances in the report itself.

Each score says plainly how it was worked out, so nobody has to trust a black box: a
category scores 10 when the nearest place is within an easy walk and falls in a straight
line to 0 at the distance most people would drive. Places come from OpenStreetMap (within
2 km), schools also from the state's school list where we have one, and the quiet score
from how close major roads, railways, industry and airports are.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.modules.property_report.schemas import ReportScore
from app.modules.property_report.sources import Nearby, Place, School

# (key, label, place keys, distance for 10, distance for 0, what it measures)
CATEGORIES: tuple[tuple[str, str, tuple[str, ...], int, int, str], ...] = (
    (
        "shops",
        "Shops and cafes",
        ("supermarket", "shops", "cafe"),
        400,
        2500,
        "supermarket, corner shop or cafe",
    ),
    (
        "transport",
        "Public transport",
        ("bus", "train"),
        250,
        1500,
        "bus stop, train, tram or ferry",
    ),
    ("schools", "Schools and childcare", ("school", "childcare"), 500, 3000, "school or childcare"),
    ("health", "Health", ("gp", "pharmacy", "hospital"), 500, 3000, "doctor, pharmacy or hospital"),
    (
        "outdoors",
        "Parks and leisure",
        ("park", "sport", "beach"),
        250,
        1500,
        "park, playground, gym, pool or beach",
    ),
)
# Everyday needs for the walk score: how many of these are within 800 m.
EVERYDAY = ("supermarket", "cafe", "pharmacy", "gp", "park", "bus", "school", "childcare")
WALK_M = 800

# (key, distance at which it stops mattering, how much it can take off out of 10)
QUIET: tuple[tuple[str, int, float], ...] = (
    ("major_road", 300, 4.0),
    ("railway", 400, 3.0),
    ("industrial", 600, 2.0),
    ("landfill", 1500, 2.0),
    ("airport", 4000, 3.0),
    ("power_line", 200, 1.0),
)


def _linear(distance: int, best: int, worst: int) -> float:
    if distance <= best:
        return 10.0
    if distance >= worst:
        return 0.0
    return 10.0 * (worst - distance) / (worst - best)


def _distance_words(metres: int) -> str:
    return f"{round(metres / 10) * 10} m" if metres < 1000 else f"{metres / 1000:.1f} km"


def neighbourhood_scores(
    places: list[Place] | None,
    schools: list[School] | None = None,
    surroundings: list[Nearby] | None = None,
) -> list[ReportScore]:
    out: list[ReportScore] = []
    if places is not None:
        nearest = {p.key: p for p in places}
        state_school = min((s.distance_m for s in schools or []), default=None)
        for key, label, keys, best, worst, what in CATEGORIES:
            distances = [nearest[k].nearest_m for k in keys if k in nearest]
            if key == "schools" and state_school is not None:
                distances.append(state_school)
            if not distances:
                out.append(
                    ReportScore(key=key, label=label, score=0.0, summary=f"No {what} within 2 km.")
                )
                continue
            d = min(distances)
            out.append(
                ReportScore(
                    key=key,
                    label=label,
                    score=round(_linear(d, best, worst), 1),
                    summary=f"Nearest {what}: {_distance_words(d)}.",
                )
            )
        close = [
            k
            for k in EVERYDAY
            if (k in nearest and nearest[k].nearest_m <= WALK_M)
            or (k == "school" and state_school is not None and state_school <= WALK_M)
        ]
        out.insert(
            0,
            ReportScore(
                key="walk",
                label="Walk to everyday needs",
                score=round(10.0 * len(close) / len(EVERYDAY), 1),
                summary=f"{len(close)} of {len(EVERYDAY)} everyday needs within a 10-minute "
                "walk (800 m): supermarket, cafe, pharmacy, doctor, park, bus stop, school "
                "and childcare.",
            ),
        )
    if surroundings is not None:
        score = 10.0
        near = []
        for key, reach, weight in QUIET:
            found = next((n for n in surroundings if n.key == key), None)
            if found is None or found.distance_m is None or found.distance_m >= reach:
                continue
            score -= weight * (reach - found.distance_m) / reach
            near.append(f"{found.label.lower()} {_distance_words(found.distance_m)}")
        out.append(
            ReportScore(
                key="quiet",
                label="Quiet streets",
                score=round(max(score, 0.0), 1),
                summary=("Nearby: " + ", ".join(near) + ".")
                if near
                else "No major road, railway, industry or airport close by.",
            )
        )
    return out


def overall(scores: Iterable[ReportScore]) -> float | None:
    values = [s.score for s in scores]
    return round(sum(values) / len(values), 1) if values else None
