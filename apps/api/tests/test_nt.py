"""The Northern Territory: the councils, packs, guides and forms."""

from __future__ import annotations

import pytest

from app.modules.councils import directory, states
from app.modules.guidance import guides
from app.modules.rules import packs


def test_every_council_area_has_an_entry() -> None:
    nt = directory.councils("NT")
    assert len(nt) == 18
    for council in nt:
        assert council.key.startswith("nt_") and council.sources, council.key
        assert council.spatial_name == council.spatial_name.upper(), council.key
    assert directory.by_key("nt_darwin") is not None
    planning = states.for_state("NT")
    assert planning is not None and planning.fees and planning.zoning_lookup_url


def test_every_nt_approval_has_a_guide() -> None:
    kinds: set[str] = set()
    for name in ("planning_nt", "property_nt", "business_nt"):
        pack = packs.load_file(name)
        for rule_set in pack.rule_sets:
            assert rule_set.jurisdiction.endswith("NT")
            for rule in rule_set.rules:
                for outcome in rule.outcomes:
                    approval = (outcome.payload or {}).get("approval")
                    if approval:
                        kinds.add(approval["kind"])
    assert kinds and all(k.startswith("NT_") for k in kinds)
    have = {g.kind for g in guides.guides()}
    assert kinds <= have, kinds - have


@pytest.mark.parametrize("name", ["planning_nt", "property_nt", "business_nt", "councils_nt"])
def test_packs_load(name: str) -> None:
    assert packs.load_file(name).key == name
