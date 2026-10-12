"""The pre-lodgement pack's sections, from facts alone (no database)."""

from __future__ import annotations

from decimal import Decimal

from app.modules.documents import prelodgement

OPTIONS = {
    "property.zone": {"low_density_residential": "Low density residential"},
    "planning.known_constraints": {"flooding": "Flooding"},
}


def test_pack_brings_in_the_site_council_and_questions() -> None:
    pack = prelodgement.build(
        {
            "property.address": {"line1": "1 Smith St", "suburb": "Edge Hill", "state": "QLD"},
            "property.lot_plan": "12RP700000",
            "property.lga": "cairns",
            "property.zone": "low_density_residential",
            "property.land_area_m2": Decimal("600.0"),
            "planning.known_constraints": ["flooding"],
        },
        OPTIONS,
        [{"title": "Building approval", "certainty_label": "Required"}],
        [{"title": "Site plan", "detail": None}],
        ["Storeys"],
    )
    site = {row["label"]: row["value"] for row in pack["site"]}
    assert site["Address"] == "1 Smith St, Edge Hill QLD"
    assert site["Council"] == "Cairns Regional Council"
    assert site["Zone"] == "Low density residential"
    assert site["Land area"] == "600 m²"
    assert pack["constraints"] == ["Flooding"]
    assert pack["council"]["email"] == "council@cairns.qld.gov.au"
    assert pack["council"]["email_general"] is True
    assert "in the Low density residential zone" in pack["questions"][0]
    assert any("flood" in q for q in pack["questions"])
    # A required approval isn't asked about; it is already known.
    assert not any("Building approval" in q for q in pack["questions"])
    assert "Site plan" in pack["bring"]
    assert pack["to_confirm"] == ["Storeys"]


def test_pack_without_a_known_council_still_has_questions() -> None:
    pack = prelodgement.build({}, {}, [], [], [])
    assert pack["council"] is None
    assert pack["site"] == [] and pack["proposal"] == []
    assert len(pack["questions"]) >= 4
