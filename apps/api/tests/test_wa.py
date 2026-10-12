"""Western Australia: the councils, packs, guides and forms. There are no address lookups for
WA: the state's address, cadastre and zoning data is licensed for personal or internal use
only (ARCHITECTURE §49)."""

from __future__ import annotations

import pytest

from app.modules.councils import directory, states
from app.modules.guidance import guides
from app.modules.rules import packs


def test_every_council_area_has_an_entry() -> None:
    wa = directory.councils("WA")
    assert len(wa) == 137
    for council in wa:
        assert council.key.startswith("wa_") and council.sources, council.key
        assert council.spatial_name == council.spatial_name.upper(), council.key
    assert directory.by_key("wa_stirling") is not None
    planning = states.for_state("WA")
    assert planning is not None and planning.fees and planning.zoning_lookup_url


def test_every_wa_approval_has_a_guide() -> None:
    kinds: set[str] = set()
    for name in ("planning_wa", "property_wa", "business_wa"):
        pack = packs.load_file(name)
        for rule_set in pack.rule_sets:
            assert rule_set.jurisdiction.endswith("WA")
            for rule in rule_set.rules:
                for outcome in rule.outcomes:
                    approval = (outcome.payload or {}).get("approval")
                    if approval:
                        kinds.add(approval["kind"])
    assert kinds and all(k.startswith("WA_") for k in kinds)
    have = {g.kind for g in guides.guides()}
    assert kinds <= have, kinds - have


@pytest.mark.parametrize("name", ["planning_wa", "property_wa", "business_wa", "councils_wa"])
def test_packs_load(name: str) -> None:
    assert packs.load_file(name).key == name
