"""Subscription tiers and feature flags for RemoteSafe.

No payment is taken in Stage 1: a platform administrator sets an organisation's tier, and
every organisation starts on Starter. ``built`` says whether the feature exists yet, so the
app never offers (or advertises) something that isn't working.
"""

from __future__ import annotations

from dataclasses import dataclass

TIERS = ("STARTER", "PROFESSIONAL", "ENTERPRISE")


@dataclass(frozen=True)
class Feature:
    key: str
    label: str
    tier: str
    built: bool


FEATURES: tuple[Feature, ...] = (
    Feature("journeys", "Journey plans and route legs", "STARTER", True),
    Feature("risk_assessment", "Rules-based risk assessment", "STARTER", True),
    Feature("controls", "Pre-departure critical controls", "STARTER", True),
    Feature("approvals", "Supervisor approval workflow", "STARTER", True),
    Feature("pdf_export", "PDF journey plans", "STARTER", True),
    Feature("gis_routes", "Map-based route analysis and overlays", "PROFESSIONAL", False),
    Feature("checkin_monitoring", "Check-in monitoring and escalation", "PROFESSIONAL", False),
    Feature("notifications", "Alerts to monitors and contacts", "PROFESSIONAL", False),
    Feature("offline", "Offline worker app", "PROFESSIONAL", False),
    Feature("departments", "Multiple departments", "ENTERPRISE", False),
    Feature("advanced_reporting", "Advanced reporting", "ENTERPRISE", False),
    Feature("satellite_devices", "Approved satellite device integrations", "ENTERPRISE", False),
    Feature("risk_library", "Configurable risk library", "ENTERPRISE", True),
    Feature("api_access", "API access", "ENTERPRISE", False),
)


def available(tier: str, feature: Feature) -> bool:
    return TIERS.index(tier) >= TIERS.index(feature.tier)


def has_feature(tier: str, key: str) -> bool:
    feature = next(f for f in FEATURES if f.key == key)
    return feature.built and available(tier, feature)


# Shown wherever RemoteSafe describes itself, until each line is no longer true.
LIMITATIONS = (
    "RemoteSafe does not replace emergency services (000) or your organisation's emergency "
    "response plan.",
    "Check-ins are planned here, but RemoteSafe does not yet receive check-ins, detect missed "
    "ones or alert anyone. Your journey monitor must follow up by phone or radio.",
    "Road closures, weather, flood, mobile coverage and remoteness are what the planner "
    "recorded and where they got it. RemoteSafe does not look them up yet.",
    "Risk ratings are a planning tool set by your organisation's policy, not a measured "
    "probability of harm.",
)
