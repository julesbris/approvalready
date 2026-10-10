import type { ProductOut } from "@approvalready/shared-types";

import { formatMoney, limitLabel, parseDollars, priceLabel, reviewPrice } from "./billing";

describe("billing labels", () => {
  it("formats money in dollars", () => {
    expect(formatMoney(24_900)).toBe("$249.00");
    expect(formatMoney(12_345_678)).toBe("$123,456.78");
    expect(formatMoney(4900, "NZD")).toBe("NZD 49.00");
    expect(priceLabel({ amount_cents: 2900, currency: "AUD", interval: "MONTH" })).toBe(
      "$29.00 a month",
    );
    expect(priceLabel({ amount_cents: 2900, currency: "AUD", interval: "ONE_TIME" })).toBe("$29.00");
  });

  it("reads the dollars staff type", () => {
    expect(parseDollars("249")).toBe(24_900);
    expect(parseDollars("$249.5")).toBe(24_950);
    expect(parseDollars(" 19.99 ")).toBe(1999);
    expect(parseDollars("0")).toBeNull();
    expect(parseDollars("12.345")).toBeNull();
    expect(parseDollars("ten")).toBeNull();
  });

  it("finds the review price for a vertical", () => {
    const price = {
      id: "p1",
      amount_cents: 24_900,
      currency: "AUD",
      interval: "ONE_TIME",
      active: true,
      created_at: "2026-10-10T00:00:00Z",
    };
    const products = [
      { key: "review.planning", prices: [price] },
      { key: "rent.manage", prices: [] },
    ] as unknown as ProductOut[];
    expect(reviewPrice(products, "PLANNING")?.id).toBe("p1");
    expect(reviewPrice(products, "VESSEL")).toBeNull();
    expect(limitLabel(null)).toBe("Unlimited");
    expect(limitLabel(10)).toBe("10");
  });
});
