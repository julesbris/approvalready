"""Marketplace analytics schemas (Milestone 16).

Rates are fractions from 0 to 1 (None when there is nothing to divide by); times are hours;
money is cents. Partner-facing shapes hold the partner's own figures and, separately,
other partners' medians that ``service.benchmark`` releases only over ``min_partners``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class FunnelOut(BaseModel):
    offered: int
    accepted: int
    declined: int
    # Offered, never answered, and the referral closed.
    missed: int
    # Offered and still open to answer.
    waiting: int
    # Accepted and not yet won or lost.
    in_progress: int
    quoted: int
    won: int
    lost: int
    accept_rate: float | None
    win_rate: float | None
    answered_within_48h_rate: float | None
    median_response_hours: float | None
    # Accepted as one of the plan's included referrals (no fee).
    included: int
    fees_cents: int
    refunded_cents: int


class CategoryFunnelOut(FunnelOut):
    category_key: str
    category_label: str


class AreaFunnelOut(FunnelOut):
    # The council area, or the postcode when the referral named no council.
    area: str
    state: str


class MonthFunnelOut(FunnelOut):
    month: str  # "2026-10", Brisbane time


class PartnerAnalyticsOut(BaseModel):
    months: int
    period_start: datetime
    period_end: datetime
    totals: FunnelOut
    by_category: list[CategoryFunnelOut]
    by_area: list[AreaFunnelOut]
    by_month: list[MonthFunnelOut]


class BenchmarkOut(BaseModel):
    """Other partners' medians. Each figure is None unless enough partners contribute."""

    category_key: str | None  # None: every category
    category_label: str
    accept_rate: float | None
    win_rate: float | None
    median_response_hours: float | None
    withheld: bool


class BenchmarksOut(BaseModel):
    min_partners: int
    rows: list[BenchmarkOut]


class MarketTotalsOut(BaseModel):
    leads: int
    # Matching ran and no partner was eligible: a gap in supply.
    no_partner_available: int
    # At least one partner accepted.
    found_partner: int
    found_partner_rate: float | None
    filled: int
    expired_unclaimed: int
    withdrawn: int
    open: int
    offers: int
    claims: int
    won: int
    lost: int
    win_rate: float | None
    median_hours_to_first_accept: float | None
    fees_cents: int
    refunded_cents: int


class MarketCategoryOut(MarketTotalsOut):
    category_key: str
    category_label: str


class MarketAreaOut(MarketTotalsOut):
    area: str
    state: str


class MarketMonthOut(MarketTotalsOut):
    month: str


class MarketPartnerOut(BaseModel):
    partner_id: uuid.UUID
    name: str
    status: str
    offered: int
    accepted: int
    declined: int
    missed: int
    won: int
    lost: int
    accept_rate: float | None
    win_rate: float | None
    answered_within_48h_rate: float | None
    median_response_hours: float | None
    fees_cents: int


class MarketplaceAnalyticsOut(BaseModel):
    months: int
    period_start: datetime
    period_end: datetime
    totals: MarketTotalsOut
    by_category: list[MarketCategoryOut]
    by_area: list[MarketAreaOut]
    by_month: list[MarketMonthOut]
    partners: list[MarketPartnerOut]
