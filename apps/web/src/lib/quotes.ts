/** Quotes (Milestone 23): statuses, GST and totals in plain words. */

import type { GstTreatment, QuoteOut, QuoteStatus } from "@approvalready/shared-types";

export const QUOTE_STATUS_LABELS: Record<QuoteStatus, string> = {
  SENT: "Waiting for an answer",
  SUPERSEDED: "Replaced by a revision",
  WITHDRAWN: "Withdrawn",
  ACCEPTED: "Accepted",
  DECLINED: "Declined",
};

export const GST_LABELS: Record<GstTreatment, string> = {
  INCLUDED: "Amounts include GST",
  EXCLUDED: "GST is added to these amounts",
  NOT_REGISTERED: "No GST (not registered for GST)",
};

/** The status a person reads: a waiting quote past its date reads as expired. */
export function quoteStatusLabel(quote: Pick<QuoteOut, "status" | "expired">): string {
  return quote.expired ? "Expired" : QUOTE_STATUS_LABELS[quote.status];
}

/** The CSS status class to show it with. */
export function quoteStatusClass(quote: Pick<QuoteOut, "status" | "expired">): string {
  return `status status-${quote.expired ? "expired" : quote.status.toLowerCase()}`;
}

/** GST and the total including it, in cents, rounded half up (as the API does). */
export function gstAmounts(totalCents: number, gst: GstTreatment): { gst: number; total: number } {
  if (gst === "INCLUDED") return { gst: Math.floor((2 * totalCents + 11) / 22), total: totalCents };
  if (gst === "EXCLUDED") {
    const tax = Math.floor((totalCents + 5) / 10);
    return { gst: tax, total: totalCents + tax };
  }
  return { gst: 0, total: totalCents };
}

/** A line amount typed by a partner ("1800", "$1,800.50", "0") to cents, or null. */
export function parseAmount(value: string): number | null {
  const cleaned = value.replace(/[$,\s]/g, "");
  if (!/^\d{1,7}(\.\d{1,2})?$/.test(cleaned)) return null;
  const cents = Math.round(Number(cleaned) * 100);
  return cents <= 100_000_000 ? cents : null;
}

/** "YYYY-MM-DD", `days` from `from` (local date). */
export function isoDateAfter(days: number, from: Date = new Date()): string {
  const d = new Date(from.getFullYear(), from.getMonth(), from.getDate() + days);
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${mm}-${dd}`;
}

/** Group quotes by the job (lead) they're for, keeping the API's newest-first order. */
export function groupByJob<T extends { lead_id: string }>(quotes: T[]): T[][] {
  const groups = new Map<string, T[]>();
  for (const q of quotes) {
    const group = groups.get(q.lead_id) ?? [];
    group.push(q);
    groups.set(q.lead_id, group);
  }
  return [...groups.values()];
}
