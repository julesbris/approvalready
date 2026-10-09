/** Labels and helpers for SellReady and RentReady (Milestone 11). */

import type {
  ApplicationOut,
  InspectionItemOut,
  ItemCondition,
  OfferStatus,
  SaleStatus,
  VaultCategory,
} from "@approvalready/shared-types";

export const SALE_STATUS_LABELS: Record<SaleStatus, string> = {
  PREPARING: "Preparing",
  READY_TO_LIST: "Ready to list",
  LISTED: "Listed",
  UNDER_OFFER: "Under offer",
  UNDER_CONTRACT: "Under contract",
  SETTLED: "Settled",
  WITHDRAWN: "Withdrawn",
};

/** Button text for moving a sale to a status. */
export const SALE_STATUS_ACTIONS: Record<SaleStatus, string> = {
  PREPARING: "Back to preparing",
  READY_TO_LIST: "Mark ready to list",
  LISTED: "Mark as listed",
  UNDER_OFFER: "Mark under offer",
  UNDER_CONTRACT: "Record a contract",
  SETTLED: "Mark as settled",
  WITHDRAWN: "Withdraw the sale",
};

export const DISCLOSURE_LABELS: Record<string, string> = {
  NOT_STARTED: "Not started",
  PREPARING: "Being prepared",
  GIVEN: "Given to the buyer",
  NOT_NEEDED: "Not needed",
};

export const VAULT_CATEGORIES: [VaultCategory, string][] = [
  ["DISCLOSURE_STATEMENT", "Disclosure statement"],
  ["TITLE_SEARCH", "Title search"],
  ["REGISTERED_PLAN", "Registered plan"],
  ["BODY_CORPORATE", "Body corporate certificate"],
  ["POOL_SAFETY", "Pool safety certificate or notice"],
  ["SMOKE_ALARMS", "Smoke alarm compliance"],
  ["BUILDING_APPROVAL", "Building approvals"],
  ["RATES_AND_WATER", "Rates and water"],
  ["PLANNING_AND_ZONING", "Planning and zoning"],
  ["TENANCY", "Tenancy agreement"],
  ["CONTRACT", "Contract"],
  ["OTHER", "Other"],
];

export function vaultCategoryLabel(category: string): string {
  return VAULT_CATEGORIES.find(([key]) => key === category)?.[1] ?? category;
}

export const OFFER_STATUS_LABELS: Record<OfferStatus, string> = {
  RECEIVED: "Received",
  COUNTERED: "Countered",
  ACCEPTED: "Accepted",
  REJECTED: "Rejected",
  WITHDRAWN: "Withdrawn",
  LAPSED: "Lapsed",
};

export const ENQUIRY_STATUS_LABELS: Record<string, string> = {
  NEW: "New",
  RESPONDED: "Responded",
  CLOSED: "Closed",
};

export const LISTING_LABELS: Record<string, string> = {
  NOT_LISTED: "Not listed",
  ADVERTISED: "Advertised",
  LEASED: "Leased",
  WITHDRAWN: "Withdrawn",
};

export const RENT_PERIOD_LABELS: Record<string, string> = {
  WEEK: "per week",
  FORTNIGHT: "per fortnight",
  MONTH: "per month",
};

export const APPLICATION_STATUS_LABELS: Record<string, string> = {
  RECEIVED: "Received",
  SHORTLISTED: "Shortlisted",
  APPROVED: "Approved",
  DECLINED: "Declined",
  WITHDRAWN: "Withdrawn",
};

export const TENANCY_STATUS_LABELS: Record<string, string> = {
  UPCOMING: "Starts soon",
  ACTIVE: "Active",
  ENDED: "Ended",
};

export const INSPECTION_KIND_LABELS: Record<string, string> = {
  ENTRY: "Entry",
  ROUTINE: "Routine",
  EXIT: "Exit",
};

export const INSPECTION_STATUS_LABELS: Record<string, string> = {
  SCHEDULED: "Scheduled",
  IN_PROGRESS: "In progress",
  COMPLETED: "Completed",
  CANCELLED: "Cancelled",
};

export const CONDITIONS: [ItemCondition, string][] = [
  ["GOOD", "Good"],
  ["FAIR", "Fair"],
  ["POOR", "Poor"],
  ["DAMAGED", "Damaged"],
  ["NOT_APPLICABLE", "N/A"],
];

export const PRIORITY_LABELS: Record<string, string> = {
  EMERGENCY: "Emergency",
  URGENT: "Urgent",
  ROUTINE: "Routine",
};

export const MAINTENANCE_STATUS_LABELS: Record<string, string> = {
  REPORTED: "Reported",
  SCHEDULED: "Booked",
  IN_PROGRESS: "In progress",
  DONE: "Done",
  CANCELLED: "Cancelled",
};

export function money(cents: number | null | undefined): string {
  if (cents === null || cents === undefined) return "";
  const whole = cents % 100 === 0;
  return new Intl.NumberFormat("en-AU", {
    style: "currency",
    currency: "AUD",
    minimumFractionDigits: whole ? 0 : 2,
    maximumFractionDigits: 2,
  }).format(cents / 100);
}

/** An inspection's items grouped by room, in list order. */
export function byRoom(items: InspectionItemOut[]): [string, InspectionItemOut[]][] {
  const rooms = new Map<string, InspectionItemOut[]>();
  for (const item of [...items].sort((a, b) => a.position - b.position)) {
    rooms.set(item.room, [...(rooms.get(item.room) ?? []), item]);
  }
  return [...rooms.entries()];
}

/** "3 of 4 documents provided" for an application. */
export function checksSummary(application: ApplicationOut): string {
  const provided = application.checks.filter((c) => c.provided === true).length;
  return `${provided} of ${application.checks.length} documents provided`;
}

/** A local date and time (from date and time inputs) as an ISO string with the offset. */
export function localDateTime(day: string, time: string): string {
  return new Date(`${day}T${time || "09:00"}`).toISOString();
}
