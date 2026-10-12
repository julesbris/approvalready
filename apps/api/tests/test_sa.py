"""South Australia: the councils, packs, guides and forms."""

from __future__ import annotations

import pytest

from app.modules.councils import directory, states
from app.modules.guidance import guides
from app.modules.rules import packs


def test_every_council_area_has_an_entry() -> None:
    wa = directory.councils("SA")
    assert len(wa) == 68
    for council in wa:
        assert council.key.startswith("sa_") and council.sources, council.key
        assert council.spatial_name == council.spatial_name.upper(), council.key
    assert directory.by_key("sa_adelaide") is not None
    planning = states.for_state("SA")
    assert planning is not None and planning.fees and planning.zoning_lookup_url


def test_every_sa_approval_has_a_guide() -> None:
    kinds: set[str] = set()
    for name in ("planning_sa", "property_sa", "business_sa"):
        pack = packs.load_file(name)
        for rule_set in pack.rule_sets:
            assert rule_set.jurisdiction.endswith("SA")
            for rule in rule_set.rules:
                for outcome in rule.outcomes:
                    approval = (outcome.payload or {}).get("approval")
                    if approval:
                        kinds.add(approval["kind"])
    assert kinds and all(k.startswith("SA_") for k in kinds)
    have = {g.kind for g in guides.guides()}
    assert kinds <= have, kinds - have


@pytest.mark.parametrize("name", ["planning_sa", "property_sa", "business_sa", "councils_sa"])
def test_packs_load(name: str) -> None:
    assert packs.load_file(name).key == name
