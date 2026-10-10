"""Marketplace analytics (Milestone 16), computed on request from the lead engine's rows.

* ``partner_report``: one partner's own referrals over a period: the funnel (offered,
  accepted, declined, missed, quoted, won, lost), response times, what it spent, and the same
  by category, by area and by month. Only that partner's rows are read.
* ``benchmarks``: how other partners in the same categories do (accept rate, win rate,
  response time), as the median across partners. A figure is shown only when at least
  ``k`` other partners contribute to it (``ANALYTICS_MIN_PARTNERS``, default 5); otherwise it
  is withheld. Nothing names or counts the other partners, and nothing per lead leaves here.
* ``marketplace_report``: staff (``lead.manage``): leads, how many found a partner, how
  fast, the fees, by category, area, month and partner. Counts only: no customer details.

Nothing is stored: every figure comes from ``lead``, ``lead_match``, ``lead_claim`` and
``lead_status_event`` at the time of the request, so it can't drift from the referrals.
"""

from __future__ import annotations

import statistics
import uuid
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.leads.matching import RESPONSE_WINDOW
from app.modules.leads.models import (
    OPEN_MATCH,
    WORKING,
    Lead,
    LeadClaim,
    LeadMatch,
    LeadMatchStatus,
    LeadStatus,
    LeadStatusEvent,
)
from app.modules.leads.service import month_start
from app.modules.marketplace.models import MarketplaceCategory
from app.modules.notifications.reminders import BRISBANE
from app.modules.partners.models import PartnerOrganisation
from app.modules.tenancy.models import Organisation

PERIODS = (1, 3, 6, 12)  # months, counting the current one
STAFF_PARTNER_ROWS = 50


def period_start(now: datetime, months: int) -> datetime:
    """The start of the Brisbane calendar month ``months - 1`` months before this one."""
    start = month_start(now)
    for _ in range(months - 1):
        start = month_start(start - timedelta(days=1))
    return start


def month_key(at: datetime) -> str:
    """'2026-10' for a time, in Brisbane."""
    return at.astimezone(BRISBANE).strftime("%Y-%m")


def months_between(start: datetime, now: datetime) -> list[str]:
    keys: list[str] = []
    at = start
    while at <= now:
        key = month_key(at)
        if key not in keys:
            keys.append(key)
        at += timedelta(days=28)
    if month_key(now) not in keys:
        keys.append(month_key(now))
    return keys


def ratio(part: int, whole: int) -> float | None:
    return round(part / whole, 3) if whole else None


def median(values: Iterable[float]) -> float | None:
    values = list(values)
    return round(statistics.median(values), 1) if values else None


def hours(delta: timedelta) -> float:
    return delta.total_seconds() / 3600


# --- One partner's own referrals --------------------------------------------------------


@dataclass
class MatchRow:
    status: str
    offered_at: datetime
    responded_at: datetime | None
    quoted: bool
    category_key: str
    category_label: str
    lga: str | None
    state: str
    postcode: str
    claimed: bool
    included: bool
    fee_cents: int
    refunded: bool


@dataclass
class Funnel:
    offered: int = 0
    accepted: int = 0
    declined: int = 0
    missed: int = 0
    waiting: int = 0
    in_progress: int = 0
    quoted: int = 0
    won: int = 0
    lost: int = 0
    answered_in_window: int = 0
    included: int = 0
    fees_cents: int = 0
    refunded_cents: int = 0
    response_hours: list[float] = field(default_factory=list)

    def add(self, row: MatchRow) -> None:
        self.offered += 1
        status = LeadMatchStatus(row.status)
        if row.claimed:
            self.accepted += 1
            if row.included:
                self.included += 1
            if row.refunded:
                self.refunded_cents += row.fee_cents
            else:
                self.fees_cents += row.fee_cents
        if status == LeadMatchStatus.DECLINED:
            self.declined += 1
        elif status == LeadMatchStatus.EXPIRED:
            self.missed += 1
        elif status in OPEN_MATCH:
            self.waiting += 1
        elif status in WORKING:
            self.in_progress += 1
        elif status == LeadMatchStatus.WON:
            self.won += 1
        elif status == LeadMatchStatus.LOST:
            self.lost += 1
        if row.quoted or status == LeadMatchStatus.QUOTED:
            self.quoted += 1
        if row.responded_at is not None:
            took = row.responded_at - row.offered_at
            self.response_hours.append(hours(took))
            if took <= RESPONSE_WINDOW:
                self.answered_in_window += 1

    def out(self) -> dict[str, Any]:
        return {
            "offered": self.offered,
            "accepted": self.accepted,
            "declined": self.declined,
            "missed": self.missed,
            "waiting": self.waiting,
            "in_progress": self.in_progress,
            "quoted": self.quoted,
            "won": self.won,
            "lost": self.lost,
            "accept_rate": ratio(self.accepted, self.offered),
            "win_rate": ratio(self.won, self.won + self.lost),
            "answered_within_48h_rate": ratio(self.answered_in_window, self.offered),
            "median_response_hours": median(self.response_hours),
            "included": self.included,
            "fees_cents": self.fees_cents,
            "refunded_cents": self.refunded_cents,
        }


def _quoted() -> Any:
    return exists().where(
        LeadStatusEvent.lead_match_id == LeadMatch.id,
        LeadStatusEvent.to_status == LeadMatchStatus.QUOTED,
    )


async def _partner_rows(db: AsyncSession, partner_id: uuid.UUID, start: datetime) -> list[MatchRow]:
    rows = await db.execute(
        select(
            LeadMatch.status,
            LeadMatch.offered_at,
            LeadMatch.responded_at,
            _quoted(),
            MarketplaceCategory.key,
            MarketplaceCategory.label,
            Lead.lga,
            Lead.state,
            Lead.postcode,
            LeadClaim.id,
            LeadClaim.included,
            LeadClaim.fee_cents,
            LeadClaim.refunded_at,
        )
        .join(Lead, Lead.id == LeadMatch.lead_id)
        .join(MarketplaceCategory, MarketplaceCategory.id == Lead.category_id)
        .outerjoin(LeadClaim, LeadClaim.lead_match_id == LeadMatch.id)
        .where(
            LeadMatch.partner_organisation_id == partner_id,
            LeadMatch.offered_at.is_not(None),
            LeadMatch.offered_at >= start,
        )
        .order_by(LeadMatch.offered_at)
    )
    return [
        MatchRow(
            status=r[0],
            offered_at=r[1],
            responded_at=r[2],
            quoted=bool(r[3]),
            category_key=r[4],
            category_label=r[5],
            lga=r[6],
            state=r[7],
            postcode=r[8],
            claimed=r[9] is not None,
            included=bool(r[10]),
            fee_cents=int(r[11] or 0),
            refunded=r[12] is not None,
        )
        for r in rows
    ]


def _grouped(
    rows: list[MatchRow], key: Callable[[MatchRow], tuple[str, ...]]
) -> list[tuple[tuple[str, ...], Funnel]]:
    groups: dict[tuple[str, ...], Funnel] = defaultdict(Funnel)
    for row in rows:
        groups[key(row)].add(row)
    return sorted(groups.items(), key=lambda kv: (-kv[1].offered, kv[0]))


def _area(row: MatchRow) -> tuple[str, ...]:
    """Council area when the lead has one, else the postcode."""
    return (row.lga or row.postcode, row.state)


async def partner_report(
    db: AsyncSession, partner: PartnerOrganisation, *, months: int, now: datetime
) -> dict[str, Any]:
    start = period_start(now, months)
    rows = await _partner_rows(db, partner.id, start)
    total = Funnel()
    for row in rows:
        total.add(row)
    by_month: dict[str, Funnel] = {key: Funnel() for key in months_between(start, now)}
    for row in rows:
        by_month.setdefault(month_key(row.offered_at), Funnel()).add(row)
    return {
        "months": months,
        "period_start": start,
        "period_end": now,
        "totals": total.out(),
        "by_category": [
            {"category_key": k[0], "category_label": k[1], **f.out()}
            for k, f in _grouped(rows, lambda r: (r.category_key, r.category_label))
        ],
        "by_area": [{"area": k[0], "state": k[1], **f.out()} for k, f in _grouped(rows, _area)],
        "by_month": [{"month": k, **f.out()} for k, f in sorted(by_month.items())],
        "categories": sorted({r.category_key for r in rows}),
    }


# --- Benchmarks (k-anonymous) ------------------------------------------------------------


@dataclass
class PartnerFigures:
    offered: int
    accepted: int
    won: int
    lost: int
    median_response_hours: float | None


async def _others(
    db: AsyncSession,
    partner_id: uuid.UUID,
    start: datetime,
    category_ids: list[uuid.UUID] | None,
) -> list[PartnerFigures]:
    """One row per other partner offered referrals in the period (in these categories)."""
    took = func.extract("epoch", LeadMatch.responded_at - LeadMatch.offered_at) / 3600
    query = (
        select(
            func.count(),
            func.count(LeadClaim.id),
            func.count().filter(LeadMatch.status == LeadMatchStatus.WON),
            func.count().filter(LeadMatch.status == LeadMatchStatus.LOST),
            func.percentile_cont(0.5)
            .within_group(took)
            .filter(LeadMatch.responded_at.is_not(None)),
        )
        .join(Lead, Lead.id == LeadMatch.lead_id)
        .outerjoin(LeadClaim, LeadClaim.lead_match_id == LeadMatch.id)
        .where(
            LeadMatch.partner_organisation_id != partner_id,
            LeadMatch.offered_at.is_not(None),
            LeadMatch.offered_at >= start,
        )
        .group_by(LeadMatch.partner_organisation_id)
    )
    if category_ids is not None:
        query = query.where(Lead.category_id.in_(category_ids))
    return [
        PartnerFigures(
            offered=int(r[0]),
            accepted=int(r[1]),
            won=int(r[2]),
            lost=int(r[3]),
            median_response_hours=float(r[4]) if r[4] is not None else None,
        )
        for r in await db.execute(query)
    ]


def _k_median(values: list[float], k: int, digits: int) -> float | None:
    """The median across partners, or None when fewer than ``k`` partners contribute."""
    if len(values) < k:
        return None
    return round(statistics.median(values), digits)


def benchmark(others: list[PartnerFigures], k: int) -> dict[str, Any]:
    accept = [o.accepted / o.offered for o in others if o.offered]
    win = [o.won / (o.won + o.lost) for o in others if o.won + o.lost]
    response = [o.median_response_hours for o in others if o.median_response_hours is not None]
    out: dict[str, Any] = {
        "accept_rate": _k_median(accept, k, 3),
        "win_rate": _k_median(win, k, 3),
        "median_response_hours": _k_median(response, k, 1),
    }
    out["withheld"] = all(v is None for v in out.values())
    return out


async def benchmarks(
    db: AsyncSession,
    partner: PartnerOrganisation,
    *,
    months: int,
    now: datetime,
    k: int,
) -> dict[str, Any]:
    """Other partners' medians, overall and for each category this partner was offered."""
    start = period_start(now, months)
    categories = (
        await db.execute(
            select(MarketplaceCategory.id, MarketplaceCategory.key, MarketplaceCategory.label)
            .where(
                MarketplaceCategory.id.in_(
                    select(Lead.category_id)
                    .join(LeadMatch, LeadMatch.lead_id == Lead.id)
                    .where(
                        LeadMatch.partner_organisation_id == partner.id,
                        LeadMatch.offered_at.is_not(None),
                        LeadMatch.offered_at >= start,
                    )
                )
            )
            .order_by(MarketplaceCategory.sort_order, MarketplaceCategory.key)
        )
    ).all()
    rows = [
        {
            "category_key": None,
            "category_label": "All categories",
            **benchmark(await _others(db, partner.id, start, None), k),
        }
    ]
    for cid, key, label in categories:
        rows.append(
            {
                "category_key": key,
                "category_label": label,
                **benchmark(await _others(db, partner.id, start, [cid]), k),
            }
        )
    return {"min_partners": k, "rows": rows}


# --- Staff: the whole marketplace --------------------------------------------------------


@dataclass
class LeadRow:
    status: str
    created_at: datetime
    category_key: str
    category_label: str
    lga: str | None
    state: str
    postcode: str
    matched: bool
    matches: int
    offered: int
    first_claim_at: datetime | None
    claims: int
    fees_cents: int
    refunded_cents: int
    won: int
    lost: int


@dataclass
class LeadTotals:
    leads: int = 0
    no_partner_available: int = 0
    found_partner: int = 0
    filled: int = 0
    expired_unclaimed: int = 0
    withdrawn: int = 0
    open: int = 0
    offers: int = 0
    claims: int = 0
    won: int = 0
    lost: int = 0
    fees_cents: int = 0
    refunded_cents: int = 0
    first_claim_hours: list[float] = field(default_factory=list)

    def add(self, row: LeadRow) -> None:
        self.leads += 1
        status = LeadStatus(row.status)
        if row.matched and row.matches == 0:
            self.no_partner_available += 1
        if row.claims:
            self.found_partner += 1
        if status == LeadStatus.FILLED:
            self.filled += 1
        elif status == LeadStatus.EXPIRED and not row.claims:
            self.expired_unclaimed += 1
        elif status == LeadStatus.WITHDRAWN:
            self.withdrawn += 1
        elif status == LeadStatus.OPEN:
            self.open += 1
        self.offers += row.offered
        self.claims += row.claims
        self.won += row.won
        self.lost += row.lost
        self.fees_cents += row.fees_cents
        self.refunded_cents += row.refunded_cents
        if row.first_claim_at is not None:
            self.first_claim_hours.append(hours(row.first_claim_at - row.created_at))

    def out(self) -> dict[str, Any]:
        return {
            "leads": self.leads,
            "no_partner_available": self.no_partner_available,
            "found_partner": self.found_partner,
            "found_partner_rate": ratio(self.found_partner, self.leads),
            "filled": self.filled,
            "expired_unclaimed": self.expired_unclaimed,
            "withdrawn": self.withdrawn,
            "open": self.open,
            "offers": self.offers,
            "claims": self.claims,
            "won": self.won,
            "lost": self.lost,
            "win_rate": ratio(self.won, self.won + self.lost),
            "median_hours_to_first_accept": median(self.first_claim_hours),
            "fees_cents": self.fees_cents,
            "refunded_cents": self.refunded_cents,
        }


async def _lead_rows(db: AsyncSession, start: datetime) -> list[LeadRow]:
    offered = (
        select(
            LeadMatch.lead_id.label("lead_id"),
            func.count().label("matches"),
            func.count().filter(LeadMatch.offered_at.is_not(None)).label("offered"),
            func.count().filter(LeadMatch.status == LeadMatchStatus.WON).label("won"),
            func.count().filter(LeadMatch.status == LeadMatchStatus.LOST).label("lost"),
        )
        .group_by(LeadMatch.lead_id)
        .subquery()
    )
    claims = (
        select(
            LeadClaim.lead_id.label("lead_id"),
            func.min(LeadClaim.created_at).label("first_at"),
            func.count().label("claims"),
            func.coalesce(
                func.sum(LeadClaim.fee_cents).filter(LeadClaim.refunded_at.is_(None)), 0
            ).label("fees"),
            func.coalesce(
                func.sum(LeadClaim.fee_cents).filter(LeadClaim.refunded_at.is_not(None)), 0
            ).label("refunded"),
        )
        .group_by(LeadClaim.lead_id)
        .subquery()
    )
    rows = await db.execute(
        select(
            Lead.status,
            Lead.created_at,
            MarketplaceCategory.key,
            MarketplaceCategory.label,
            Lead.lga,
            Lead.state,
            Lead.postcode,
            Lead.matched_at,
            func.coalesce(offered.c.matches, 0),
            func.coalesce(offered.c.offered, 0),
            claims.c.first_at,
            func.coalesce(claims.c.claims, 0),
            func.coalesce(claims.c.fees, 0),
            func.coalesce(claims.c.refunded, 0),
            func.coalesce(offered.c.won, 0),
            func.coalesce(offered.c.lost, 0),
        )
        .join(MarketplaceCategory, MarketplaceCategory.id == Lead.category_id)
        .outerjoin(offered, offered.c.lead_id == Lead.id)
        .outerjoin(claims, claims.c.lead_id == Lead.id)
        .where(Lead.created_at >= start)
        .order_by(Lead.created_at)
    )
    return [
        LeadRow(
            status=r[0],
            created_at=r[1],
            category_key=r[2],
            category_label=r[3],
            lga=r[4],
            state=r[5],
            postcode=r[6],
            matched=r[7] is not None,
            matches=int(r[8]),
            offered=int(r[9]),
            first_claim_at=r[10],
            claims=int(r[11]),
            fees_cents=int(r[12]),
            refunded_cents=int(r[13]),
            won=int(r[14]),
            lost=int(r[15]),
        )
        for r in rows
    ]


def _lead_groups(
    rows: list[LeadRow], key: Callable[[LeadRow], tuple[str, ...]]
) -> list[tuple[tuple[str, ...], LeadTotals]]:
    groups: dict[tuple[str, ...], LeadTotals] = defaultdict(LeadTotals)
    for row in rows:
        groups[key(row)].add(row)
    return sorted(groups.items(), key=lambda kv: (-kv[1].leads, kv[0]))


async def _staff_partners(db: AsyncSession, start: datetime) -> list[dict[str, Any]]:
    took = func.extract("epoch", LeadMatch.responded_at - LeadMatch.offered_at) / 3600
    in_window = and_(
        LeadMatch.responded_at.is_not(None),
        LeadMatch.responded_at - LeadMatch.offered_at <= RESPONSE_WINDOW,
    )
    rows = await db.execute(
        select(
            PartnerOrganisation.id,
            Organisation.name,
            PartnerOrganisation.verification_status,
            func.count(),
            func.count(LeadClaim.id),
            func.count().filter(LeadMatch.status == LeadMatchStatus.DECLINED),
            func.count().filter(LeadMatch.status == LeadMatchStatus.EXPIRED),
            func.count().filter(LeadMatch.status == LeadMatchStatus.WON),
            func.count().filter(LeadMatch.status == LeadMatchStatus.LOST),
            func.count().filter(in_window),
            func.percentile_cont(0.5)
            .within_group(took)
            .filter(LeadMatch.responded_at.is_not(None)),
            func.coalesce(func.sum(LeadClaim.fee_cents).filter(LeadClaim.refunded_at.is_(None)), 0),
        )
        .join(PartnerOrganisation, PartnerOrganisation.id == LeadMatch.partner_organisation_id)
        .join(Organisation, Organisation.id == PartnerOrganisation.organisation_id)
        .outerjoin(LeadClaim, LeadClaim.lead_match_id == LeadMatch.id)
        .where(LeadMatch.offered_at.is_not(None), LeadMatch.offered_at >= start)
        .group_by(
            PartnerOrganisation.id, Organisation.name, PartnerOrganisation.verification_status
        )
        .order_by(func.count().desc(), Organisation.name)
        .limit(STAFF_PARTNER_ROWS)
    )
    out = []
    for r in rows:
        offered, accepted, won, lost = int(r[3]), int(r[4]), int(r[7]), int(r[8])
        out.append(
            {
                "partner_id": r[0],
                "name": r[1],
                "status": r[2],
                "offered": offered,
                "accepted": accepted,
                "declined": int(r[5]),
                "missed": int(r[6]),
                "won": won,
                "lost": lost,
                "accept_rate": ratio(accepted, offered),
                "win_rate": ratio(won, won + lost),
                "answered_within_48h_rate": ratio(int(r[9]), offered),
                "median_response_hours": round(float(r[10]), 1) if r[10] is not None else None,
                "fees_cents": int(r[11]),
            }
        )
    return out


async def marketplace_report(db: AsyncSession, *, months: int, now: datetime) -> dict[str, Any]:
    start = period_start(now, months)
    rows = await _lead_rows(db, start)
    total = LeadTotals()
    for row in rows:
        total.add(row)
    by_month: dict[str, LeadTotals] = {key: LeadTotals() for key in months_between(start, now)}
    for row in rows:
        by_month.setdefault(month_key(row.created_at), LeadTotals()).add(row)
    return {
        "months": months,
        "period_start": start,
        "period_end": now,
        "totals": total.out(),
        "by_category": [
            {"category_key": k[0], "category_label": k[1], **t.out()}
            for k, t in _lead_groups(rows, lambda r: (r.category_key, r.category_label))
        ],
        "by_area": [
            {"area": k[0], "state": k[1], **t.out()}
            for k, t in _lead_groups(rows, lambda r: (r.lga or r.postcode, r.state))
        ],
        "by_month": [{"month": k, **t.out()} for k, t in sorted(by_month.items())],
        "partners": await _staff_partners(db, start),
    }
