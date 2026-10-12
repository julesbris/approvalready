import type { PlusOfferOut } from "@approvalready/shared-types";
import { describe, expect, it } from "vitest";

import { longDate, plusPrice, trialTimeline } from "@/lib/membership";

const OFFER: PlusOfferOut = {
  on_sale: true,
  product_name: "ApprovalReady Plus",
  description: "",
  amount_cents: 2900,
  currency: "AUD",
  interval: "MONTH",
  trial_days: 30,
  reminder_days: 7,
};

describe("ApprovalReady Plus", () => {
  it("shows the price a month, or nothing before staff set one", () => {
    expect(plusPrice(OFFER)).toBe("$29.00 a month");
    expect(plusPrice({ ...OFFER, amount_cents: null, interval: null })).toBeNull();
  });

  it("lays out the free month: nothing today, a reminder, then the first charge", () => {
    expect(trialTimeline(OFFER, true)).toEqual([
      { when: "Today", what: "Add your card. Your free month starts.", amount: "$0.00" },
      {
        when: "Day 23",
        what: "We email you a reminder 7 days before the first charge",
        amount: "$0.00",
      },
      { when: "Day 31", what: "First charge, then every month", amount: "$29.00" },
    ]);
  });

  it("skips the reminder row for a short trial and the free rows without one", () => {
    const week = trialTimeline({ ...OFFER, trial_days: 7 }, true);
    expect(week.map((r) => r.when)).toEqual(["Today", "Day 8"]);
    expect(trialTimeline(OFFER, false)).toEqual([
      { when: "Today", what: "Your membership starts", amount: "$29.00" },
    ]);
  });

  it("writes dates out in full, in Brisbane time", () => {
    expect(longDate("2026-11-10T20:00:00Z")).toBe("Wednesday 11 November 2026");
  });
});
