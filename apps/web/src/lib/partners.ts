/** Partner accounts (Milestone 14): statuses, credentials and service areas in plain words. */

import type {
  AustralianState,
  MembershipOut,
  PartnerCategoryStatus,
  PartnerCredentialKind,
  PartnerCredentialStatus,
  PartnerServiceAreaOut,
  PartnerStatus,
  ServiceAreaKind,
  SessionOut,
} from "@approvalready/shared-types";

export const PARTNER_STATUS_LABELS: Record<PartnerStatus, string> = {
  APPLIED: "Application received",
  UNDER_REVIEW: "Being checked",
  ACTIVE: "Approved",
  SUSPENDED: "Suspended",
  REJECTED: "Not approved",
};

export const CATEGORY_STATUS_LABELS: Record<PartnerCategoryStatus, string> = {
  PENDING: "Waiting for our check",
  APPROVED: "Approved",
  REJECTED: "Not approved",
};

export const CREDENTIAL_KIND_LABELS: Record<PartnerCredentialKind, string> = {
  LICENCE: "Licence or registration",
  ACCREDITATION: "Accreditation",
  PI_INSURANCE: "Professional indemnity insurance",
  PL_INSURANCE: "Public liability insurance",
};

export const CREDENTIAL_STATUS_LABELS: Record<PartnerCredentialStatus, string> = {
  UNVERIFIED: "Waiting for our check",
  VERIFIED: "Checked",
  REJECTED: "Not accepted",
};

export const AREA_KIND_LABELS: Record<ServiceAreaKind, string> = {
  POSTCODE: "Postcode",
  LGA: "Council area",
  STATE: "Whole state",
};

export const STATES: AustralianState[] = ["QLD", "NSW", "VIC", "SA", "WA", "TAS", "NT", "ACT"];

export function areaLabel(area: Pick<PartnerServiceAreaOut, "kind" | "state" | "value">): string {
  if (area.kind === "STATE") return `All of ${area.state}`;
  if (area.kind === "POSTCODE") return `${area.value} ${area.state}`;
  return `${area.value} (council area, ${area.state})`;
}

/** The plan limits' features, in words for the partner. */
export const LIMIT_LABELS: Record<string, string> = {
  "partner.categories.max": "Categories that receive referrals",
  "partner.service_areas.max": "Service areas that receive referrals",
  "partner.members.max": "People in your account",
};

/** The user's partner organisations. */
export function partnerOrganisations(session: SessionOut): MembershipOut[] {
  return session.organisations.filter((o) => o.kind === "PARTNER");
}

/** The active organisation, when it is a partner organisation. */
export function activePartnerOrganisation(session: SessionOut): MembershipOut | null {
  return (
    partnerOrganisations(session).find(
      (o) => o.organisation_id === session.active_organisation_id,
    ) ?? null
  );
}

/** Dollars of insurance cover ("20000000" or "$20,000,000") to cents, or null. */
export function parseCover(value: string): number | null {
  const digits = value.replace(/[$,\s]/g, "");
  if (!/^\d{1,9}$/.test(digits)) return null;
  const cents = Number(digits) * 100;
  return cents > 0 ? cents : null;
}

/** "$20m" style cover for lists. */
export function formatCover(cents: number): string {
  const dollars = cents / 100;
  if (dollars >= 1_000_000 && dollars % 1_000_000 === 0) return `$${dollars / 1_000_000}m`;
  return `$${dollars.toLocaleString("en-AU")}`;
}
