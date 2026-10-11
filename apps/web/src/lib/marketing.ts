import type {
  MarketingChannel,
  MarketingPostStatus,
  NewsletterSubscriberOut,
} from "@approvalready/shared-types";

/** Marketing admin: labels and the Brisbane-time helpers its forms use. */

export const CHANNELS: MarketingChannel[] = ["FACEBOOK", "INSTAGRAM", "EMAIL"];

export const CHANNEL_LABELS: Record<MarketingChannel, string> = {
  FACEBOOK: "Facebook",
  INSTAGRAM: "Instagram",
  EMAIL: "Email list",
};

export const POST_STATUS_LABELS: Record<MarketingPostStatus, string> = {
  SCHEDULED: "Scheduled",
  PUBLISHING: "Posting now",
  POSTED: "Posted",
  FAILED: "Failed",
  CANCELLED: "Cancelled",
};

/** Status chip class (globals.css maps `status-<status>` to a colour). */
export function postStatusClass(status: MarketingPostStatus): string {
  const tone: Record<MarketingPostStatus, string> = {
    SCHEDULED: "status-open",
    PUBLISHING: "status-in_progress",
    POSTED: "status-completed",
    FAILED: "status-failed",
    CANCELLED: "status-cancelled",
  };
  return `status ${tone[status]}`;
}

/** ISO weekdays, Monday first. */
export const WEEKDAYS: [number, string][] = [
  [1, "Mon"],
  [2, "Tue"],
  [3, "Wed"],
  [4, "Thu"],
  [5, "Fri"],
  [6, "Sat"],
  [7, "Sun"],
];

/** Instagram allows 2,200 characters; Facebook posts are kept to 2,000. */
export const CAPTION_LIMITS: Partial<Record<MarketingChannel, number>> = {
  FACEBOOK: 2000,
  INSTAGRAM: 2200,
};

// Queensland has no daylight saving: Brisbane is always UTC+10.
const BRISBANE_OFFSET_MS = 10 * 60 * 60 * 1000;

/** A `datetime-local` value ("2026-10-12T09:00") in Brisbane time for an instant. */
export function toBrisbaneInput(date: Date): string {
  return new Date(date.getTime() + BRISBANE_OFFSET_MS).toISOString().slice(0, 16);
}

/** The ISO instant for a `datetime-local` value read as Brisbane time, or null. */
export function fromBrisbaneInput(value: string): string | null {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) return null;
  const at = new Date(`${value}:00+10:00`);
  return Number.isNaN(at.getTime()) ? null : at.toISOString();
}

/** "Mon 12 Oct 2026, 9:00 am" in Brisbane time. */
export function formatBrisbane(iso: string): string {
  return new Intl.DateTimeFormat("en-AU", {
    timeZone: "Australia/Brisbane",
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(iso));
}

/** "09:00:00" from the API as "09:00" for a time input. */
export function timeInput(value: string): string {
  return value.slice(0, 5);
}

/** The guide ref in a card file name ("guide-x.jpg"), or null for anything else. */
export function cardRef(file: string): string | null {
  const match = /^([a-z0-9-]{1,120})\.jpg$/.exec(file);
  return match?.[1] ?? null;
}

export const SUBSCRIBER_STATUS_LABELS: Record<NewsletterSubscriberOut["status"], string> = {
  PENDING: "Waiting to confirm",
  SUBSCRIBED: "Subscribed",
  UNSUBSCRIBED: "Unsubscribed",
};
