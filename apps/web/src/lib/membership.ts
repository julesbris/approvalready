/** ApprovalReady Plus: the membership with a free first month, in plain words. */

import type { PlusOfferOut } from "@approvalready/shared-types";

import { INTERVAL_SUFFIX, formatMoney } from "@/lib/billing";

export const PLUS_BENEFITS = [
  "An online project plan for every project, at no extra cost",
  "Every step from your checklist on a timeline, in the order to do them, with suggested dates",
  "The forms, fees, contacts and timeframes right next to each step, with links to the official pages",
  "A due date, an owner and notes on each step, and your files kept against it",
  "Checked partners in your area suggested for each part, with their phone, email and website",
  "Follow-up calls added in one click, with an email reminder on the day",
];

/** "$29.00 a month", or null while it has no price. */
export function plusPrice(offer: PlusOfferOut): string | null {
  if (offer.amount_cents === null || offer.interval === null) return null;
  return `${formatMoney(offer.amount_cents, offer.currency ?? "AUD")}${INTERVAL_SUFFIX[offer.interval]}`;
}

export type TimelineRow = { when: string; what: string; amount: string };

/** What happens and what is charged, from today to the first charge. */
export function trialTimeline(offer: PlusOfferOut, trial: boolean): TimelineRow[] {
  const amount =
    offer.amount_cents === null
      ? "Price to come"
      : formatMoney(offer.amount_cents, offer.currency ?? "AUD");
  if (!trial || offer.trial_days === 0) {
    return [{ when: "Today", what: "Your membership starts", amount }];
  }
  const days = offer.trial_days;
  const reminderDay = Math.max(1, days - offer.reminder_days);
  const rows: TimelineRow[] = [
    { when: "Today", what: "Add your card. Your free month starts.", amount: formatMoney(0) },
  ];
  if (reminderDay > 1) {
    rows.push({
      when: `Day ${reminderDay}`,
      what: `We email you a reminder ${offer.reminder_days} days before the first charge`,
      amount: formatMoney(0),
    });
  }
  rows.push({
    when: `Day ${days + 1}`,
    what: `First charge, then ${offer.interval === "YEAR" ? "every year" : "every month"}`,
    amount,
  });
  return rows;
}

/** "Tuesday 11 November 2026", in Brisbane time. */
export function longDate(iso: string): string {
  return new Intl.DateTimeFormat("en-AU", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "Australia/Brisbane",
  }).format(new Date(iso));
}
