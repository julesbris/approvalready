"""The process-wide lookup clients, created with the app and closed with it."""

from __future__ import annotations

import httpx

from app.core.config import Settings
from app.modules.lookups.amsa import AmsaVesselList
from app.modules.lookups.client import create_http_client
from app.modules.lookups.qld import QldSpatial


class Lookups:
    def __init__(
        self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.enabled = settings.lookups_enabled
        self.http = create_http_client(settings, transport)
        self.qld = QldSpatial(self.http, settings.qld_spatial_base_url)
        self.amsa = AmsaVesselList(self.http, settings)

    async def aclose(self) -> None:
        await self.http.aclose()
