"""The process-wide lookup clients, created with the app and closed with it."""

from __future__ import annotations

import httpx

from app.core.config import Settings
from app.modules.lookups.abs import AbsPostcodes
from app.modules.lookups.amsa import AmsaVesselList
from app.modules.lookups.client import create_http_client
from app.modules.lookups.listing import DomainListings
from app.modules.lookups.nsw import NswSpatial
from app.modules.lookups.qld import QldSpatial
from app.modules.lookups.spatial import StateSpatial
from app.modules.property_report.sources import AbsCensus, Overpass, QldSchoolsAndFlood, QpsCrime


class Lookups:
    def __init__(
        self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.enabled = settings.lookups_enabled
        self.http = create_http_client(settings, transport)
        self.qld = QldSpatial(self.http, settings.qld_spatial_base_url)
        # Every state whose addresses and parcels we can look up, by state code.
        self.nsw = NswSpatial(
            self.http, settings.nsw_spatial_base_url, settings.nsw_planning_base_url
        )
        self.states: dict[str, StateSpatial] = {"QLD": self.qld, "NSW": self.nsw}
        self.amsa = AmsaVesselList(self.http, settings)
        self.postcodes = AbsPostcodes(self.http, settings.abs_geo_base_url)
        key = settings.domain_api_key.get_secret_value() if settings.domain_api_key else None
        self.domain = DomainListings(self.http, settings.domain_api_base_url, key)
        # The free property report's sources (app/modules/property_report).
        self.census = AbsCensus(
            self.http, settings.abs_geo_base_url, settings.abs_data_api_base_url
        )
        self.schools = QldSchoolsAndFlood(self.http, settings.qld_spatial_base_url)
        self.places = Overpass(self.http, settings.overpass_url)
        self.crime = QpsCrime(self.http, settings.qps_crime_data_base_url)

    def for_state(self, state: str | None) -> StateSpatial | None:
        return self.states.get((state or "").upper())

    async def aclose(self) -> None:
        await self.http.aclose()
