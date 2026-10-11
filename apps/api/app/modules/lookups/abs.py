"""Postcodes for Queensland addresses, from the Australian Bureau of Statistics' postal
areas (ASGS 2021 ``POA``, free, no key, ``geo.abs.gov.au``).

The state's address data has no postcodes, so an address's point is placed in the ABS
postal area that contains it. Postal areas are the ABS's approximation of Australia Post
postcodes, built from whole mesh blocks: almost always the same, occasionally not near a
postcode boundary. The web app fills the postcode in for the customer to check, never as a
fact anything is decided on.
"""

from __future__ import annotations

import httpx

from app.modules.lookups.client import TtlCache

POSTAL_AREAS = "ASGS2021/POA/MapServer/0"
POSTCODE_SOURCE = "Australian Bureau of Statistics postal areas (ASGS 2021)"


class AbsPostcodes:
    def __init__(self, http: httpx.AsyncClient, base_url: str) -> None:
        self.http = http
        self.base_url = base_url.rstrip("/")
        self._cache = TtlCache(max_entries=2048, ttl_seconds=7 * 24 * 3600)

    async def postcode_at(self, latitude: float, longitude: float) -> str | None:
        """The postcode of the postal area containing a point, or None when there isn't
        one or the service didn't answer (a postcode is a convenience: people can type it)."""
        key = f"{latitude:.5f},{longitude:.5f}"
        cached = self._cache.get(key)
        if cached is not None:
            return str(cached) or None
        try:
            response = await self.http.get(
                f"{self.base_url}/{POSTAL_AREAS}/query",
                params={
                    "geometry": f"{longitude},{latitude}",
                    "geometryType": "esriGeometryPoint",
                    "inSR": "4326",
                    "spatialRel": "esriSpatialRelIntersects",
                    "outFields": "poa_code_2021",
                    "returnGeometry": "false",
                    "f": "json",
                },
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        features = body.get("features") if isinstance(body, dict) else None
        code = None
        if features:
            value = str((features[0].get("attributes") or {}).get("poa_code_2021") or "")
            code = value if value.isdigit() and len(value) == 4 else None
        self._cache.put(key, code or "")
        return code
