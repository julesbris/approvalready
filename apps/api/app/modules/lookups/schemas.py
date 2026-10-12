from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class AddressMatchOut(BaseModel):
    address_pid: int = Field(description="Queensland address identifier.")
    label: str
    line1: str
    suburb: str
    state: str
    postcode: str | None = Field(
        description="From the ABS postal area containing the address (check it)."
    )
    lot_plan: str | None = Field(description="Lot and plan in the cadastre, e.g. 2RP53576.")
    lot_plan_label: str | None = Field(description="e.g. 'Lot 2 on RP53576'.")
    local_authority: str | None = Field(description="Council, e.g. 'Cairns Regional'.")
    lga: str | None = Field(description="The planning questionnaire's council answer.")
    latitude: float | None
    longitude: float | None


class AddressSearchOut(BaseModel):
    matches: list[AddressMatchOut]
    source: str
    note: str


class OverlayOut(BaseModel):
    key: str
    label: str
    group: str
    constraint: str | None = Field(
        description="The planning.known_constraints option it supports, if any."
    )
    source_url: str


class NotCheckedOut(BaseModel):
    label: str
    why: str
    where_to_check: str | None


class ParcelOut(BaseModel):
    lot: str
    plan: str
    lot_plan: str
    lot_plan_label: str
    tenure: str | None
    land_area_m2: Decimal | None
    locality: str | None
    local_authority: str | None
    lga: str | None
    parcel_type: str | None
    overlays: list[OverlayOut] = Field(description="State-mapped overlays the parcel touches.")
    overlays_checked: list[str] = Field(description="Mapping groups that were checked.")
    overlays_failed: list[str] = Field(description="Mapping groups whose service didn't answer.")
    not_checked: list[NotCheckedOut] = Field(description="Things to check elsewhere.")
    source: str
    source_url: str
    retrieved_at: datetime


class VesselLookupOut(BaseModel):
    uvi: str
    name: str | None
    displayed_identifier: str | None
    length_m: str | None
    fields: dict[str, str] = Field(description="Every published column, by AMSA's header.")
    source: str
    source_url: str
    list_retrieved_at: datetime
    note: str


class ListingIn(BaseModel):
    url: str = Field(min_length=4, max_length=2000)


class ListingDetailsOut(BaseModel):
    bedrooms: int | None
    bathrooms: int | None
    car_spaces: int | None
    property_type: str | None
    price_text: str | None = Field(description="The advertised price, as the listing shows it.")
    headline: str | None
    status: str | None
    objective: str | None = Field(description="'sale' or 'rent'.")


class ListingImportOut(BaseModel):
    site: str = Field(description="Which site the link is from, e.g. 'domain', 'realestate'.")
    site_name: str
    how: str = Field(description="What we may read from that site, in plain words.")
    url: str
    address_text: str | None = Field(description="The address as the link spells it.")
    property_type: str | None = Field(description="From the link or the listing.")
    details: ListingDetailsOut | None = Field(
        description="From Domain's developer API, when the server has a key."
    )
    matches: list[AddressMatchOut] = Field(description="Queensland addresses to pick from.")
    note: str
