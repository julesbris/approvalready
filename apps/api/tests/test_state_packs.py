"""Every state's content pack loads into the database and publishes, the way the deploy
script loads it (a pack that validates as JSON can still be refused by the rule gate)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app import cli
from app.modules.regulatory.service import Actor
from app.modules.rules import packs
from app.modules.tenancy.models import Organisation
from tests.harness import ApiHarness, platform_user

STATE_PACKS = [
    name
    for name in packs.available()
    if name.split("_")[0] in ("planning", "property", "business")
    and name.rsplit("_", 1)[-1] not in ("qld", "cairns")
]


@pytest.mark.asyncio
@pytest.mark.parametrize("name", STATE_PACKS)
async def test_state_pack_loads_and_publishes(api: ApiHarness, name: str) -> None:
    admin = await platform_user(api, "ADMIN")
    pack = packs.load_file(name)
    suffix = uuid.uuid4().hex[:8]
    for rs in pack.rule_sets:
        rs.key = f"{rs.key}_{suffix}"
    for program in pack.grant_programs:
        program.key = f"{program.key}_{suffix}"
        program.rule_set = f"{program.rule_set}_{suffix}"
    factory = api.app.state.resources.session_factory
    async with factory() as db:
        org = (
            await db.execute(select(Organisation).where(Organisation.kind == "PLATFORM_ADMIN"))
        ).scalar_one()
        report = await packs.load(
            db, pack, Actor(uuid.UUID(admin.id), org.id, cli.CLI_META), publish=True
        )
        assert report.not_published == [], report.lines()
        await db.rollback()
