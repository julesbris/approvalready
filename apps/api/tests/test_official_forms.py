"""Official forms: every numbered form our guidance names links to that form, within the
guide or product that names it, and the API serves the links."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any

import pytest

from app.modules.checklists import definition as checklists
from app.modules.guidance import forms, guides
from app.modules.guidance.forms import OfficialForm
from app.modules.rules import packs
from tests.harness import ApiHarness

# How form numbers are written in our text: "Form 18a", "DA Form 1", "B650", "F3518",
# "NAT 75163", "HW019", "AR01".
NUMBERED = re.compile(
    r"(?<![\w])(?:DA )?Form [0-9]+[a-z]?(?![\w])"
    r"|(?<![\w])(?:B[0-9]{3}[A-Za-z]{0,2}|F[0-9]{4}|NAT [0-9]{4,5}|HW[0-9]{3}|AR[0-9]{2})(?![\w])"
)
# Named but deliberately not linked: B709DA and B709X are no longer valid (the guide says
# so), "B709" alone is Queensland Police's online permit (its step links that service), and
# the building guide's plumbing "Form 19" is a council plumbing certificate, not the
# Building Act's Form 19.
NOT_LINKED = {("RESTRICTED_GOODS_PERMISSION", n) for n in ("B709", "B709DA", "B709X")}
NOT_LINKED |= {("BUILDING_APPROVAL", "Form 19")}


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def _unlinked(texts: list[str], scope: list[OfficialForm]) -> set[str]:
    """Form numbers in these texts that no form in scope links."""
    missing: set[str] = set()
    for text in texts:
        covered: list[tuple[int, int]] = []
        for f in scope:
            for phrase in f.phrases:
                pattern = rf"(?<![\w]){re.escape(phrase)}(?![\w])"
                covered += [(m.start(), m.end()) for m in re.finditer(pattern, text)]
        for m in NUMBERED.finditer(text):
            if not any(a <= m.start() and m.end() <= b for a, b in covered):
                missing.add(m.group(0))
    return missing


def test_catalogue_is_well_formed() -> None:
    lib = forms.library()
    assert len(lib.forms) >= 60
    for f in lib.forms:
        assert f.url.startswith("https://"), f.id
        assert f.phrases, f"{f.id}: nothing in our text would link to it"


def test_every_form_a_guide_names_is_linked() -> None:
    for guide in guides.guides():
        scope = forms.by_ids(guide.forms)
        texts = list(_strings(guide.model_dump(mode="json", exclude={"sources", "forms"})))
        missing = {n for n in _unlinked(texts, scope) if (guide.kind, n) not in NOT_LINKED}
        assert not missing, f"{guide.kind}: add {sorted(missing)} to its forms"
        # Every form the guide lists is one it actually names.
        for f in scope:
            assert forms.mentioned(" ".join(texts), [f]), f"{guide.kind}: never names {f.id}"


@pytest.mark.parametrize("pack_key", ("property_qld", "vessel_au_qld", "business_qld_cairns"))
def test_every_form_a_rule_names_is_linked_in_its_product(pack_key: str) -> None:
    loaded = packs.load_file(pack_key)
    for rs in loaded.rule_sets:
        scope = forms.for_vertical(rs.vertical)
        texts = [
            t
            for r in rs.rules
            for o in r.outcomes
            for t in [r.title, o.title, o.detail, *_strings(o.payload or {})]
            if t
        ]
        missing = _unlinked(texts, scope)
        assert not missing, f"{rs.key}: no {rs.vertical} form for {sorted(missing)}"


def test_every_form_a_checklist_names_is_linked_in_its_product() -> None:
    for c in checklists.bundled().values():
        texts = [c.description, *(t for i in c.items for t in (i.title, i.detail) if t)]
        missing = _unlinked(texts, forms.for_vertical(c.vertical))
        assert not missing, f"{c.key}: no {c.vertical} form for {sorted(missing)}"


def test_same_number_links_to_the_right_form_in_each_product() -> None:
    # "Form 2" is the bond lodgement form when renting and the disclosure statement when selling.
    rent = forms.mentioned("Lodge the bond with Form 2", forms.for_vertical("RENT"))
    sell = forms.mentioned("Give the buyer a Form 2", forms.for_vertical("SELL"))
    assert [f.id for f in rent] == ["rta-form-2"]
    assert [f.id for f in sell] == ["qld-seller-disclosure-form-2"]
    # A number never matches inside a longer one.
    assert forms.mentioned("Form 18a and Form 1a", forms.for_vertical("RENT")) == [
        forms.get("rta-form-18a"),
        forms.get("rta-form-1a"),
    ]


def test_council_steps_link_the_state_forms() -> None:
    from app.modules.councils import states

    for planning in states.all_states():
        state = forms.by_ids(planning.forms)
        assert [f.id for f in state] == list(planning.forms)
        assert not _unlinked(list(planning.general_steps), state), planning.state


@pytest.mark.asyncio
async def test_api_serves_forms_and_guides_carry_theirs(api: ApiHarness) -> None:
    r = await api.client.get("/v1/guidance/forms")
    assert r.status_code == 401

    user = await api.user()
    r = await user.get("/v1/guidance/forms", params={"vertical": "RENT"})
    assert r.status_code == 200, r.text
    ids = {f["id"] for f in r.json()}
    assert "rta-form-18a" in ids and "qld-seller-disclosure-form-2" not in ids

    r = await user.get("/v1/guidance/approvals", params={"kind": "IMPORT_DECLARATION"})
    assert r.status_code == 200, r.text
    (guide,) = r.json()
    b650 = next(f for f in guide["forms"] if f["id"] == "abf-b650")
    assert b650["code"] == "B650" and b650["url"].startswith("https://www.abf.gov.au/")
    assert json.dumps(guide).count("B650") > 1


def test_plan_steps_that_name_a_form_link_to_it() -> None:
    from app.modules.plans.checklist import Section, Step, _link_forms

    section = Section(
        key="checklist:sell.qld_disclosure",
        kind="CHECKLIST",
        title="Disclosure",
        steps=[
            Step(key="a", kind="CHECK", title="Check and sign the disclosure statement (Form 2)"),
            Step(key="b", kind="CHECK", title="Book a pest inspection"),
            Step(key="c", kind="CHECK", title="Pool: Form 36", link_url="https://x.example"),
        ],
    )
    _link_forms(section, forms.for_vertical("SELL"), every=False)
    first, second, third = section.steps
    assert first.link_url == forms.get("qld-seller-disclosure-form-2").url
    assert first.link_label == "Form 2 Seller disclosure statement"
    assert second.link_url is None
    assert third.link_url == "https://x.example"  # an existing link stays
    assert [f["url"] for f in section.forms] == [
        forms.get("qld-seller-disclosure-form-2").url,
        forms.get("qbcc-form-36").url,
    ]
