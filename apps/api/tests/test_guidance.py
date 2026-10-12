"""Approval guides: one step-by-step guide for every approval the business and trade packs
can name, kept in step with the ``guides_au`` content pack, and served in plan order with
whether a person has checked them."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app import cli
from app.modules.guidance import guides, pack
from app.modules.regulatory.service import Actor
from app.modules.rules import packs
from app.modules.tenancy.models import Organisation
from tests.harness import ApiHarness, platform_user
from tests.regulatory_helpers import ADMIN, snapshot, unique

GUIDED_PACKS = ("trade_au", "business_qld_cairns", "planning_nsw", "property_nsw", "business_nsw")


def _approval_kinds(pack_key: str) -> set[str]:
    loaded = packs.load_file(pack_key)
    return {
        o.payload["approval"]["kind"]
        for rs in loaded.rule_sets
        for r in rs.rules
        for o in r.outcomes
        if o.payload and o.payload.get("approval")
    }


@pytest.mark.parametrize("pack_key", GUIDED_PACKS)
def test_every_approval_in_the_pack_has_a_guide(pack_key: str) -> None:
    have = {g.kind for g in guides.guides()}
    missing = _approval_kinds(pack_key) - have
    assert not missing, f"{pack_key}: no guide for {sorted(missing)}"


def test_guides_are_complete_and_well_formed() -> None:
    priced = (
        "$",
        "free",
        "no charge",
        "no fee",
        "nil",
        "%",
        "fee unit",
        "depends",
        "varies",
        "see ",
    )
    for guide in guides.guides():
        assert guide.steps, guide.kind
        assert all(s.url.startswith("https://") for s in guide.sources), guide.kind
        for fee in guide.fees:
            assert any(p in fee.amount.lower() for p in priced), f"{guide.kind}: {fee.amount!r}"
        # A guide without fees or contacts says why in its gaps rather than leaving it blank.
        if not guide.fees or not guide.contacts:
            assert guide.gaps, f"{guide.kind}: missing fees or contacts need a gap"


def test_guides_come_back_in_plan_order() -> None:
    found = guides.for_kinds(["QLD_VEHICLE_REGISTRATION", "VEHICLE_IMPORT_APPROVAL", "NOPE"])
    assert [g.kind for g in found] == ["VEHICLE_IMPORT_APPROVAL", "QLD_VEHICLE_REGISTRATION"]
    orders = [g.order for g in guides.guides()]
    assert orders == sorted(orders)


def test_pack_is_in_step_with_the_guides() -> None:
    assert pack.PACK_FILE.read_text(encoding="utf-8") == pack.render(), (
        "Run `python -m app.modules.guidance.pack` after editing approval_guides.json"
    )
    loaded = packs.load_file(pack.PACK_KEY)
    assert loaded.rule_sets == []
    assert {r.section for r in loaded.references} == {g.reference_section for g in guides.guides()}
    assert all(r.extracted_text.startswith("[Gathered by ApprovalReady") for r in loaded.references)


@pytest.mark.asyncio
async def test_api_serves_guides_for_the_kinds_asked(api: ApiHarness) -> None:
    r = await api.client.get("/v1/guidance/approvals")
    assert r.status_code == 401

    user = await api.user()
    r = await user.get(
        "/v1/guidance/approvals",
        params=[("kind", "QLD_VEHICLE_REGISTRATION"), ("kind", "VEHICLE_IMPORT_APPROVAL")],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert [g["kind"] for g in body] == ["VEHICLE_IMPORT_APPROVAL", "QLD_VEHICLE_REGISTRATION"]
    assert body[0]["checked"] == {"verified": False, "verified_at": None}
    assert body[0]["steps"] and body[0]["sources"]

    r = await user.get("/v1/guidance/approvals")
    assert len(r.json()) == len(guides.guides())


@pytest.mark.asyncio
async def test_guide_reads_as_checked_once_its_reference_is_verified(api: ApiHarness) -> None:
    guide = guides.for_kinds(["ABN_REGISTRATION"])[0]
    staff = await platform_user(api)
    r = await staff.post(
        f"{ADMIN}/source-organisations",
        json={"name": unique("Test Agency"), "kind": "CTH_AGENCY", "jurisdiction": "CTH"},
    )
    assert r.status_code == 201, r.text
    r = await staff.post(
        f"{ADMIN}/source-documents",
        json={
            "source_organisation_id": r.json()["id"],
            "jurisdiction": "CTH",
            "title": "Test guide page",
            "url": f"https://example.com/{unique('guide')}",
            "source_type": "WEBPAGE",
        },
    )
    assert r.status_code == 201, r.text
    document = r.json()
    r = await staff.post(
        f"{ADMIN}/source-documents/{document['id']}/references",
        json={"section": guide.reference_section, "extracted_text": "Example extract."},
    )
    assert r.status_code == 201, r.text
    reference = r.json()
    await snapshot(staff, document["id"])
    r = await staff.post(
        f"{ADMIN}/source-references/{reference['id']}/review", json={"action": "VERIFY"}
    )
    assert r.status_code == 200, r.text

    user = await api.user()
    r = await user.get("/v1/guidance/approvals", params={"kind": guide.kind})
    assert r.status_code == 200, r.text
    assert r.json()[0]["checked"]["verified"] is True
    assert r.json()[0]["checked"]["verified_at"]


@pytest.mark.asyncio
async def test_pack_loads_unverified_and_only_once(api: ApiHarness) -> None:
    admin = await platform_user(api, "ADMIN")
    loaded = packs.load_file(pack.PACK_KEY)
    factory = api.app.state.resources.session_factory
    async with factory() as db:
        org = (
            await db.execute(select(Organisation).where(Organisation.kind == "PLATFORM_ADMIN"))
        ).scalar_one()
        actor = Actor(uuid.UUID(admin.id), org.id, cli.CLI_META)
        report = await packs.load(db, loaded, actor, publish=True)
        assert report.not_published == [] and report.published == []
        again = await packs.load(db, loaded, actor, publish=True)
        assert again.created == []
        await db.rollback()
