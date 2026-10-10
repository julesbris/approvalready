/** Referrals (Milestone 15): statuses, timing, money and ranking factors in plain words. */

import type {
  CreditKind,
  LeadMatchStatus,
  LeadPublicView,
  LeadStatus,
  ReleasableField,
  Timing,
} from "@approvalready/shared-types";

export const TIMING_LABELS: Record<Timing, string> = {
  ASAP: "As soon as possible",
  WITHIN_3_MONTHS: "Within 3 months",
  LATER: "Later than 3 months",
  RESEARCHING: "Just researching",
};

export const FIELD_LABELS: Record<ReleasableField, string> = {
  name: "Your name",
  email: "Email",
  phone: "Phone",
  site_address: "Site address",
};

/** The order the consent form offers contact details in. */
export const RELEASABLE_FIELDS: ReleasableField[] = ["name", "phone", "email", "site_address"];

/** What the customer sees for each request. */
export const LEAD_STATUS_LABELS: Record<LeadStatus, string> = {
  OPEN: "Finding partners",
  FILLED: "Partners found",
  EXPIRED: "Ended",
  WITHDRAWN: "Withdrawn",
};

/** What the partner sees for each referral. */
export const MATCH_STATUS_LABELS: Record<LeadMatchStatus, string> = {
  MATCHED: "New",
  VIEWED: "Viewed",
  CLAIMED: "Accepted",
  CONTACTED: "Contacted",
  QUOTED: "Quoted",
  WON: "Won",
  LOST: "Lost",
  EXPIRED: "No longer available",
  DECLINED: "Declined",
};

export const OPEN_MATCH: LeadMatchStatus[] = ["MATCHED", "VIEWED"];
export const WORKING: LeadMatchStatus[] = ["CLAIMED", "CONTACTED", "QUOTED"];

/** The outcomes a partner can record next, from each status. */
export const NEXT_OUTCOMES: Partial<Record<LeadMatchStatus, LeadMatchStatus[]>> = {
  CLAIMED: ["CONTACTED", "QUOTED", "WON", "LOST"],
  CONTACTED: ["QUOTED", "WON", "LOST"],
  QUOTED: ["WON", "LOST"],
};

export const CREDIT_KIND_LABELS: Record<CreditKind, string> = {
  PURCHASE: "Credit bought",
  PROMO: "Credit from us",
  LEAD_CHARGE: "Referral fee",
  REFUND: "Fee refunded",
  ADJUSTMENT: "Correction",
};

export const FACTOR_LABELS: Record<string, string> = {
  area: "Area",
  specialist: "Specialist",
  insurance: "Insurance",
  response: "Response",
  capacity: "Capacity",
};

/** "$25.00", "-$25.00". */
export function money(cents: number): string {
  const sign = cents < 0 ? "-" : "";
  const dollars = Math.abs(cents) / 100;
  return `${sign}$${dollars.toLocaleString("en-AU", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/** Dollars typed by staff ("25", "$25.50") to cents, or null. */
export function parseDollars(value: string): number | null {
  const cleaned = value.replace(/[$,\s]/g, "");
  if (!/^\d{1,6}(\.\d{1,2})?$/.test(cleaned)) return null;
  const cents = Math.round(Number(cleaned) * 100);
  return cents > 0 ? cents : null;
}

/** "Edge Hill, Cairns Regional Council QLD 4870" (whatever parts the lead has). */
export function leadPlace(lead: Pick<LeadPublicView, "suburb" | "lga" | "state" | "postcode">) {
  const parts = [lead.suburb, lead.lga].filter(Boolean).join(", ");
  return parts ? `${parts} ${lead.state} ${lead.postcode}` : `${lead.state} ${lead.postcode}`;
}

/** Group a partner's referrals: open offers, accepted ones still in progress, and the rest. */
export function groupOffers<T extends { lead: Pick<LeadPublicView, "status" | "lead_status"> }>(
  offers: T[],
): { open: T[]; working: T[]; closed: T[] } {
  const open: T[] = [];
  const working: T[] = [];
  const closed: T[] = [];
  for (const o of offers) {
    if (OPEN_MATCH.includes(o.lead.status) && o.lead.lead_status === "OPEN") open.push(o);
    else if (WORKING.includes(o.lead.status)) working.push(o);
    else closed.push(o);
  }
  return { open, working, closed };
}
