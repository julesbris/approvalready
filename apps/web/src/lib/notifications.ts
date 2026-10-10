/** Notification preferences (Milestone 21): what each category and channel means to people. */

import type {
  NotificationCategory,
  NotificationChannel,
  PreferenceOut,
} from "@approvalready/shared-types";

export const CATEGORY_LABELS: Record<NotificationCategory, { title: string; detail: string }> = {
  REMINDERS: {
    title: "Reminders",
    detail: "Reminders you set on projects, certificate expiry, and sale and rental dates.",
  },
  GRANT_ROUNDS: {
    title: "Grant rounds",
    detail: "When a grant program your project matched opens or is about to close.",
  },
  REFERRALS: {
    title: "Referrals",
    detail: "Requests offered to your business, and when a professional accepts your request.",
  },
  SOURCE_REVIEWS: {
    title: "Source reviews (staff)",
    detail: "Weekly note of verified sources due for review.",
  },
};

export const CHANNEL_LABELS: Record<NotificationChannel, string> = {
  ALL: "Email and in the app",
  IN_APP: "In the app only",
  OFF: "Off",
};

/** The categories a person can see: source reviews only for platform staff. */
export function visiblePreferences(items: PreferenceOut[], isStaff: boolean): PreferenceOut[] {
  return items.filter((p) => isStaff || p.category !== "SOURCE_REVIEWS");
}
