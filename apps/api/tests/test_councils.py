"""The Queensland council directory: one entry per council area in the state's address
data, matched from the address lookup's council name, kept in step with the planning
questionnaire and the ``councils_qld`` content pack, and served with whether a person has
checked it."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app import cli
from app.modules.councils import directory, pack
from app.modules.lookups.qld import lga_answer, not_checked
from app.modules.questionnaires.definition import load_bundled
from app.modules.regulatory.service import Actor
from app.modules.rules import packs
from app.modules.tenancy.models import Organisation
from tests.harness import ApiHarness, platform_user
from tests.regulatory_helpers import ADMIN, snapshot, unique

# Every council name in the state's cadastre (``shire_name``), read 2026-10-11, except the
# "Queensland Extent" placeholder. 77 local government areas plus Weipa Town.
SPATIAL_NAMES = """Aurukun Shire|Balonne Shire|Banana Shire|Barcaldine Regional|Barcoo Shire|
Blackall Tambo Regional|Boulia Shire|Brisbane City|Bulloo Shire|Bundaberg Regional|
Burdekin Shire|Burke Shire|Cairns Regional|Carpentaria Shire|Cassowary Coast Regional|
Central Highlands Regional|Charters Towers Regional|Cherbourg Aboriginal Shire|
Cloncurry Shire|Cook Shire|Croydon Shire|Diamantina Shire|Doomadgee Aboriginal Shire|
Douglas Shire|Etheridge Shire|Flinders Shire|Fraser Coast Regional|Gladstone Regional|
Gold Coast City|Goondiwindi Regional|Gympie Regional|Hinchinbrook Shire|
Hope Vale Aboriginal Shire|Ipswich City|Isaac Regional|Kowanyama Aboriginal Shire|
Livingstone Shire|Lockhart River Aboriginal Shire|Lockyer Valley Regional|Logan City|
Longreach Regional|Mackay Regional|Mapoon Aboriginal Shire|Maranoa Regional|Mareeba Shire|
McKinlay Shire|Moreton Bay City|Mornington Shire|Mount Isa City|Murweh Shire|
Napranum Aboriginal Shire|Noosa Shire|North Burnett Regional|
Northern Peninsula Area Regional|Palm Island Aboriginal Shire|Paroo Shire|
Pormpuraaw Aboriginal Shire|Quilpie Shire|Redland City|Richmond Shire|Rockhampton Regional|
Scenic Rim Regional|Somerset Regional|South Burnett Regional|Southern Downs Regional|
Sunshine Coast Regional|Tablelands Regional|Toowoomba Regional|Torres Shire|
Torres Strait Island Regional|Townsville City|Weipa Town|Western Downs Regional|
Whitsunday Regional|Winton Shire|Woorabinda Aboriginal Shire|Wujal Wujal Aboriginal Shire|
Yarrabah Aboriginal Shire"""


def _spatial_names() -> list[str]:
    return [n.strip() for n in SPATIAL_NAMES.replace("\n", "").split("|")]


def test_every_council_area_has_an_entry() -> None:
    names = _spatial_names()
    assert len(names) == 78
    assert sorted(c.spatial_name for c in directory.councils()) == sorted(names)
    for name in names:
        council = directory.for_local_authority(name)
        assert council is not None, name
        assert council.sources, f"{council.key} has no sources"
        # A council that publishes no steps or fees says so rather than leaving it blank.
        if not council.steps or council.fees is None or not council.lodgement:
            assert council.gaps, f"{council.key}: missing details need a gap explaining why"


def test_council_names_match_in_any_form() -> None:
    assert directory.for_local_authority("Cairns Regional").key == "cairns"  # type: ignore[union-attr]
    assert directory.for_local_authority("CAIRNS REGIONAL").key == "cairns"  # type: ignore[union-attr]
    assert directory.for_local_authority("Cairns Regional Council").key == "cairns"  # type: ignore[union-attr]
    assert directory.for_local_authority("Blackall Tambo Regional").key == "blackall_tambo"  # type: ignore[union-attr]
    assert directory.for_local_authority("Queensland Extent") is None
    assert directory.for_local_authority(None) is None
    assert lga_answer("Brisbane City") == "brisbane"
    assert lga_answer("Somewhere Else") is None


def test_not_checked_points_at_the_councils_planning_scheme() -> None:
    zone = not_checked("Cairns Regional")[0]
    assert zone.where_to_check and "cairns.qld.gov.au" in zone.where_to_check
    scheme = directory.by_key("brisbane").planning_scheme  # type: ignore[union-attr]
    assert not_checked("Brisbane City")[0].where_to_check == (scheme.url if scheme else None)


def test_fees_and_links_are_well_formed() -> None:
    priced = ("$", "free", "no charge", "cost")
    for council in directory.councils():
        if council.fees:
            for item in council.fees.items:
                assert any(p in item.amount.lower() for p in priced), (
                    f"{council.key}: {item.amount!r}"
                )
        for way in council.lodgement:
            if way.method == "EMAIL":
                assert way.email and "@" in way.email, f"{council.key}: {way.label}"


def test_planning_questionnaire_offers_every_council() -> None:
    planning = next(d for d in load_bundled() if d.key == "planning.general")
    question = next(q for q in planning.questions() if q.key == "property.lga")
    options = {o.value: o.label for o in question.options}
    assert options.pop("other") == "A council outside Queensland"
    assert options == {c.key: c.name for c in directory.councils()}


def test_pack_is_in_step_with_the_directory() -> None:
    assert pack.PACK_FILE.read_text(encoding="utf-8") == pack.render(), (
        "Run `python -m app.modules.councils.pack` after editing qld_councils.json"
    )
    loaded = packs.load_file(pack.PACK_KEY)
    assert loaded.rule_sets == []
    assert len(loaded.organisations) == len(directory.councils())
    sections = {r.section for r in loaded.references}
    assert sections == {c.reference_section for c in directory.councils()}
    assert all(r.extracted_text.startswith("[Gathered by ApprovalReady") for r in loaded.references)


@pytest.mark.asyncio
async def test_api_lists_and_shows_councils(api: ApiHarness) -> None:
    r = await api.client.get("/v1/councils")
    assert r.status_code == 401

    user = await api.user()
    r = await user.get("/v1/councils")
    assert r.status_code == 200, r.text
    assert len(r.json()) == 78
    assert {"key": "cairns", "name": directory.by_key("cairns").name} in r.json()  # type: ignore[union-attr]

    r = await user.get("/v1/councils/toowoomba")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["checked"] == {"verified": False, "verified_at": None}
    assert body["general_steps"] and body["general_source"]["url"].startswith("https://")
    assert body["sources"]

    assert (await user.get("/v1/councils/nowhere")).status_code == 404


@pytest.mark.asyncio
async def test_council_reads_as_checked_once_its_reference_is_verified(api: ApiHarness) -> None:
    council = directory.by_key("isaac")
    assert council is not None
    staff = await platform_user(api)
    r = await staff.post(
        f"{ADMIN}/source-organisations",
        json={"name": unique("Test Council"), "kind": "COUNCIL", "jurisdiction": "QLD"},
    )
    assert r.status_code == 201, r.text
    r = await staff.post(
        f"{ADMIN}/source-documents",
        json={
            "source_organisation_id": r.json()["id"],
            "jurisdiction": pack.jurisdiction(council),
            "title": "Test council directory page",
            "url": "https://example.com/council-directory",
            "source_type": "WEBPAGE",
        },
    )
    assert r.status_code == 201, r.text
    document = r.json()
    r = await staff.post(
        f"{ADMIN}/source-documents/{document['id']}/references",
        json={"section": council.reference_section, "extracted_text": "Example extract."},
    )
    assert r.status_code == 201, r.text
    reference = r.json()
    await snapshot(staff, document["id"])
    r = await staff.post(
        f"{ADMIN}/source-references/{reference['id']}/review", json={"action": "VERIFY"}
    )
    assert r.status_code == 200, r.text

    user = await api.user()
    r = await user.get("/v1/councils/isaac")
    assert r.status_code == 200, r.text
    assert r.json()["checked"]["verified"] is True
    assert r.json()["checked"]["verified_at"]


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
        assert sum(r.startswith("reference ") for r in report.created) == len(loaded.references)
        again = await packs.load(db, loaded, actor, publish=True)
        assert again.created == []
        await db.rollback()
