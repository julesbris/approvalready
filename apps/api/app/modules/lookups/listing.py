"""Bringing a property in from a listing link someone pastes (Domain, realestate.com.au,
Homely and the other free property sites).

What we may and may not do, site by site:

* **Domain** publishes a developer API (developer.domain.com.au). With a key in the server's
  settings, a domain.com.au listing's bedrooms, bathrooms, car spaces, property type and
  advertised price come from that API, which is the permitted way to read them.
* **realestate.com.au, Homely, onthehouse, property.com.au, propertyvalue, view.com.au,
  allhomes** and the rest have no public API for this, and their terms forbid copying their
  pages by software. So we never fetch the page: the address is read from the **link
  itself**, which the person gave us, and everything else is filled in from our own
  lookups (the Queensland address and parcel data, overlays, census and the rest of the
  property report).
* A link with no address in it (realestate.com.au buy and rent listings carry only the
  suburb; Facebook Marketplace and Gumtree carry neither) gives what it has, and the person
  picks the address from the search.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote, urlsplit

import httpx

from app.modules.lookups.client import LookupUnavailable, TtlCache

STATES = ("qld", "nsw", "vic", "sa", "wa", "tas", "nt", "act")


@dataclass(frozen=True)
class Site:
    key: str
    name: str
    hosts: tuple[str, ...]
    # How we read from it, in words the customer sees.
    how: str


DOMAIN = Site(
    "domain",
    "Domain",
    ("domain.com.au",),
    "Domain has an official developer API, so we can bring in the listing's details.",
)
NO_COPYING = (
    "{name}'s terms don't allow other sites to copy its listings, so we only read the "
    "address from the link and look up the rest ourselves."
)
SITES: tuple[Site, ...] = (
    DOMAIN,
    Site("realestate", "realestate.com.au", ("realestate.com.au",), NO_COPYING),
    Site("homely", "Homely", ("homely.com.au",), NO_COPYING),
    Site("onthehouse", "OnTheHouse", ("onthehouse.com.au",), NO_COPYING),
    Site("property_com_au", "property.com.au", ("property.com.au",), NO_COPYING),
    Site("propertyvalue", "PropertyValue", ("propertyvalue.com.au",), NO_COPYING),
    Site("view", "view.com.au", ("view.com.au", "realestateview.com.au"), NO_COPYING),
    Site("allhomes", "Allhomes", ("allhomes.com.au",), NO_COPYING),
    Site("rent", "rent.com.au", ("rent.com.au",), NO_COPYING),
    Site("ratemyagent", "RateMyAgent", ("ratemyagent.com.au",), NO_COPYING),
    Site(
        "facebook",
        "Facebook Marketplace",
        ("facebook.com", "fb.com"),
        "Facebook links don't include the address. Search for it below.",
    ),
    Site(
        "gumtree",
        "Gumtree",
        ("gumtree.com.au",),
        "Gumtree links don't include the address. Search for it below.",
    ),
)
OTHER = Site(
    "other",
    "that site",
    (),
    "We read the address from the link where it has one, and look up the rest ourselves.",
)

# "12-smith-street-cairns-north-qld-4870" anywhere in a path segment.
_STATE = "(?P<state>" + "|".join(STATES) + ")"
_STATE_POSTCODE = re.compile(r"^(?P<words>.+?)-" + _STATE + r"-(?P<pc>\d{4})")
# property.com.au and view.com.au: /qld/cairns-north-4870/smith-st/12-pid-123/
_SUBURB_POSTCODE = re.compile(r"^(?P<suburb>[a-z][a-z-]*?)-(?P<pc>\d{4})$")
# realestate.com.au listings: /property-house-qld-cairns+north-143123456
_REA_LISTING = re.compile(
    r"^property-(?P<type>[a-z]+)-" + _STATE + r"-(?P<suburb>[a-z+-]+?)-(?P<id>\d{6,})$"
)
# Domain listings end in the listing id: /12-smith-street-cairns-north-qld-4870-2019123456
_DOMAIN_ID = re.compile(r"-(\d{7,})$")
_ID_TAIL = re.compile(r"-(?:pid-)?\d{5,}$")

PROPERTY_TYPES = {
    "house": "House",
    "unit": "Unit",
    "apartment": "Apartment",
    "townhouse": "Townhouse",
    "villa": "Villa",
    "land": "Land",
    "acreage": "Acreage",
    "rural": "Rural",
    "studio": "Studio",
    "duplex": "Duplex",
    "terrace": "Terrace",
    "semi": "Semi-detached",
    "retire": "Retirement living",
    "blockofunits": "Block of units",
    "unitblock": "Block of units",
}


@dataclass(frozen=True)
class ListingLink:
    site: Site
    url: str
    listing_id: str | None = None
    # Read from the link: a search for the address search, and what it's made of.
    address_text: str | None = None
    suburb: str | None = None
    state: str | None = None
    postcode: str | None = None
    property_type: str | None = None


@dataclass(frozen=True)
class ListingDetails:
    """What Domain's API says about a listing."""

    bedrooms: int | None = None
    bathrooms: int | None = None
    car_spaces: int | None = None
    property_type: str | None = None
    price_text: str | None = None
    headline: str | None = None
    status: str | None = None
    objective: str | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _site_for(host: str) -> Site:
    host = host.lower().removeprefix("www.").removeprefix("m.")
    for site in SITES:
        if any(host == h or host.endswith("." + h) for h in site.hosts):
            return site
    return OTHER


def _words(slug: str) -> str:
    return " ".join(w for w in re.split(r"[-+_\s]+", slug) if w).strip()


def _title(text: str) -> str:
    return " ".join(
        w.upper() if re.fullmatch(r"\d+[a-z]?", w) else w.capitalize() for w in text.split()
    )


def parse_listing_url(raw: str) -> ListingLink | None:
    """What a pasted link tells us, read from the link alone (no request is made), or None
    when it isn't a web link."""
    text = raw.strip()
    if not re.match(r"^https?://", text, re.I):
        text = "https://" + text
    try:
        parts = urlsplit(text)
    except ValueError:
        return None
    if not parts.hostname or "." not in parts.hostname:
        return None
    site = _site_for(parts.hostname)
    segments = [unquote(s).lower() for s in parts.path.split("/") if s]
    url = f"https://{parts.hostname.lower()}{parts.path}"

    listing_id = None
    if site is DOMAIN and segments:
        found = _DOMAIN_ID.search(segments[-1])
        listing_id = found.group(1) if found else None

    if site.key == "realestate":
        for seg in segments:
            rea = _REA_LISTING.match(seg)
            if rea:
                suburb = _title(_words(rea["suburb"]))
                return ListingLink(
                    site=site,
                    url=url,
                    listing_id=rea["id"],
                    address_text=f"{suburb} {rea['state'].upper()}",
                    suburb=suburb,
                    state=rea["state"].upper(),
                    property_type=PROPERTY_TYPES.get(rea["type"]),
                )

    # Most sites: one segment holds the whole address, ending in state and postcode.
    for seg in segments:
        match = _STATE_POSTCODE.match(seg)
        if match:
            words = _words(match["words"])
            return ListingLink(
                site=site,
                url=url,
                listing_id=listing_id,
                address_text=f"{_title(words)} {match['state'].upper()} {match['pc']}",
                state=match["state"].upper(),
                postcode=match["pc"],
            )

    # property.com.au / view.com.au: state, then suburb-postcode, then street and number.
    for i, seg in enumerate(segments[:-1]):
        if seg in STATES:
            sub = _SUBURB_POSTCODE.match(segments[i + 1])
            if not sub:
                continue
            suburb = _title(_words(sub["suburb"]))
            rest = [_ID_TAIL.sub("", s) for s in segments[i + 2 :]]
            rest = [s for s in rest if s]
            street = ""
            if len(rest) >= 2 and re.match(r"^\d", rest[-1]):
                street = f"{_words(rest[-1])} {_words(rest[-2])}"  # number, then street
            elif rest:
                street = _words(rest[-1]) if re.match(r"^\d", rest[-1]) else ""
            text_parts = [_title(street)] if street else []
            return ListingLink(
                site=site,
                url=url,
                listing_id=listing_id,
                address_text=" ".join([*text_parts, suburb, seg.upper(), sub["pc"]]),
                suburb=suburb,
                state=seg.upper(),
                postcode=sub["pc"],
            )
    return ListingLink(site=site, url=url, listing_id=listing_id)


def _int(value: Any) -> int | None:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    return number if 0 <= number <= 100 else None


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _type_label(value: str | None) -> str | None:
    if not value:
        return None
    key = re.sub(r"[^a-z]", "", value.lower())
    for prefix, label in PROPERTY_TYPES.items():
        if key.startswith(prefix):
            return label
    return re.sub(r"(?<!^)(?=[A-Z])", " ", value).capitalize()


def domain_details(body: dict[str, Any]) -> ListingDetails:
    """Domain's ``GET /v1/listings/{id}`` answer, kept to what a property record needs."""
    types = body.get("propertyTypes") or []
    price = body.get("priceDetails") or {}
    parts = body.get("addressParts") or {}
    geo = body.get("geoLocation") or {}
    return ListingDetails(
        bedrooms=_int(body.get("bedrooms")),
        bathrooms=_int(body.get("bathrooms")),
        car_spaces=_int(body.get("carspaces")),
        property_type=_type_label(types[0] if types and isinstance(types[0], str) else None),
        price_text=(str(price.get("displayPrice")).strip() or None)
        if price.get("displayPrice")
        else None,
        headline=(str(body["headline"]).strip()[:200] or None) if body.get("headline") else None,
        status=str(body["status"]) if body.get("status") else None,
        objective=str(body["objective"]) if body.get("objective") else None,
        address=str(parts["displayAddress"]) if parts.get("displayAddress") else None,
        latitude=_float(geo.get("latitude")),
        longitude=_float(geo.get("longitude")),
    )


class DomainListings:
    """Domain's developer API, used only when a key is configured."""

    def __init__(self, http: httpx.AsyncClient, base_url: str, api_key: str | None) -> None:
        self.http = http
        self.base_url = base_url.rstrip("/")
        self.api_key = (api_key or "").strip() or None
        self._cache = TtlCache(max_entries=512, ttl_seconds=6 * 3600)

    @property
    def enabled(self) -> bool:
        return self.api_key is not None

    async def listing(self, listing_id: str) -> ListingDetails | None:
        if not self.api_key or not listing_id.isdigit():
            return None
        cached = self._cache.get(listing_id)
        if cached is not None:
            return cached  # type: ignore[no-any-return]
        try:
            response = await self.http.get(
                f"{self.base_url}/v1/listings/{listing_id}",
                headers={"X-Api-Key": self.api_key, "accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise LookupUnavailable("domain") from exc
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise LookupUnavailable(f"domain {response.status_code}")
        try:
            body = response.json()
        except ValueError as exc:
            raise LookupUnavailable("domain json") from exc
        if not isinstance(body, dict):
            raise LookupUnavailable("domain shape")
        details = domain_details(body)
        self._cache.put(listing_id, details)
        return details
