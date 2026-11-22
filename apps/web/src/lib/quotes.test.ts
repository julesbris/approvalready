import { describe, expect, it } from "vitest";

import {
  endsSoon,
  groupByJob,
  gstAmounts,
  isoDateAfter,
  parseAmount,
  quoteStatusLabel,
} from "./quotes";

describe("quote helpers", () => {
  it("works out GST like the API", () => {
    expect(gstAmounts(110000, "INCLUDED")).toEqual({ gst: 10000, total: 110000 });
    expect(gstAmounts(100000, "EXCLUDED")).toEqual({ gst: 10000, total: 110000 });
    expect(gstAmounts(5, "EXCLUDED")).toEqual({ gst: 1, total: 6 });
    expect(gstAmounts(12345, "NOT_REGISTERED")).toEqual({ gst: 0, total: 12345 });
  });

  it("reads line amounts, allowing zero", () => {
    expect(parseAmount("1800")).toBe(180000);
    expect(parseAmount("$1,800.50")).toBe(180050);
    expect(parseAmount("0")).toBe(0);
    expect(parseAmount("ten")).toBeNull();
    expect(parseAmount("1000000.01")).toBeNull();
  });

  it("shows a waiting quote past its date as expired", () => {
    expect(quoteStatusLabel({ status: "SENT", expired: false })).toBe("Waiting for an answer");
    expect(quoteStatusLabel({ status: "SENT", expired: true })).toBe("Expired");
    expect(quoteStatusLabel({ status: "ACCEPTED", expired: false })).toBe("Accepted");
  });

  it("dates a quote ahead", () => {
    expect(isoDateAfter(30, new Date(2026, 9, 10))).toBe("2026-11-09");
  });

  it("groups quotes by job in order", () => {
    const q = (id: string, lead_id: string) => ({ id, lead_id });
    expect(
      groupByJob([q("a", "x"), q("b", "y"), q("c", "x")]).map((g) => g.map((i) => i.id)),
    ).toEqual([["a", "c"], ["b"]]);
  });
});

describe("endsSoon", () => {
  const q = { status: "SENT" as const, expired: false };
  it("flags a waiting quote in its last three days", () => {
    expect(endsSoon({ ...q, valid_until: "2026-11-22" }, "2026-11-22")).toBe("Ends today");
    expect(endsSoon({ ...q, valid_until: "2026-11-23" }, "2026-11-22")).toBe("Ends tomorrow");
    expect(endsSoon({ ...q, valid_until: "2026-11-25" }, "2026-11-22")).toBe("Ends in 3 days");
    expect(endsSoon({ ...q, valid_until: "2026-11-26" }, "2026-11-22")).toBeNull();
  });
  it("says nothing for answered or expired quotes", () => {
    const accepted = { ...q, status: "ACCEPTED" as const, valid_until: "2026-11-22" };
    expect(endsSoon(accepted, "2026-11-22")).toBeNull();
    expect(endsSoon({ ...q, expired: true, valid_until: "2026-11-20" }, "2026-11-22")).toBeNull();
  });
});
