/** Payments (Milestone 13): money, intervals and statuses in plain words. */

import type {
  PriceInterval,
  PriceOut,
  ProductOut,
  SubscriptionOut,
} from "@approvalready/shared-types";

/** "$249.00" for AUD; other currencies keep their code ("NZD 49.00"). */
export function formatMoney(cents: number, currency = "AUD"): string {
  const amount = (cents / 100).toLocaleString("en-AU", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return currency === "AUD" ? `$${amount}` : `${currency} ${amount}`;
}

export const INTERVAL_SUFFIX: Record<PriceInterval, string> = {
  ONE_TIME: "",
  MONTH: " a month",
  YEAR: " a year",
};

export function priceLabel(price: Pick<PriceOut, "amount_cents" | "currency" | "interval">): string {
  return `${formatMoney(price.amount_cents, price.currency)}${INTERVAL_SUFFIX[price.interval]}`;
}

export const SUBSCRIPTION_STATUS_LABELS: Record<SubscriptionOut["status"], string> = {
  INCOMPLETE: "Waiting for payment",
  INCOMPLETE_EXPIRED: "Not started (payment not completed)",
  TRIALING: "Trial",
  ACTIVE: "Active",
  PAST_DUE: "Payment overdue",
  CANCELED: "Cancelled",
  UNPAID: "Unpaid",
  PAUSED: "Paused",
};

export const PAYMENT_STATUS_LABELS: Record<string, string> = {
  PENDING: "Waiting for payment",
  PAID: "Paid",
  FAILED: "Payment failed",
  CANCELLED: "Cancelled",
  REFUNDED: "Refunded",
  PARTIALLY_REFUNDED: "Partly refunded",
};

export const INVOICE_STATUS_LABELS: Record<string, string> = {
  DRAFT: "Draft",
  OPEN: "Due",
  PAID: "Paid",
  VOID: "Void",
  UNCOLLECTIBLE: "Written off",
};

/** The price of a professional review for a vertical, when one is on sale. */
export function reviewPrice(products: ProductOut[], vertical: string): PriceOut | null {
  const product = products.find((p) => p.key === `review.${vertical.toLowerCase()}`);
  return product?.prices.find((p) => p.active && p.interval === "ONE_TIME") ?? null;
}

/** Dollars typed by staff ("249" or "249.50") to cents, or null when it isn't an amount. */
export function parseDollars(value: string): number | null {
  const match = /^\s*\$?\s*(\d{1,7})(?:\.(\d{1,2}))?\s*$/.exec(value);
  if (!match) return null;
  const cents = Number(match[1]) * 100 + Number((match[2] ?? "").padEnd(2, "0"));
  return cents > 0 ? cents : null;
}

export function limitLabel(limit: number | null | undefined): string {
  return limit === null || limit === undefined ? "Unlimited" : String(limit);
}
