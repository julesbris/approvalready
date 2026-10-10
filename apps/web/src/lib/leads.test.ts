import { describe, expect, it } from "vitest";

import { groupOffers, leadPlace, money, parseDollars } from "./leads";

describe("referral helpers", () => {
  it("formats money in Australian dollars", () => {
    expect(money(2500)).toBe("$25.00");
    expect(money(-123456)).toBe("-$1,234.56");
    expect(money(0)).toBe("$0.00");
  });

  it("reads dollar amounts typed by staff", () => {
    expect(parseDollars("25")).toBe(2500);
    expect(parseDollars("$1,250.5")).toBe(125050);
    expect(parseDollars("0")).toBeNull();
    expect(parseDollars("ten")).toBeNull();
    expect(parseDollars("1.234")).toBeNull();
  });

  it("names a lead's place from the parts it has", () => {
    expect(
      leadPlace({ suburb: "Edge Hill", lga: "Cairns Regional Council", state: "QLD", postcode: "4870" }),
    ).toBe("Edge Hill, Cairns Regional Council QLD 4870");
    expect(leadPlace({ suburb: null, lga: null, state: "QLD", postcode: "4870" })).toBe(
      "QLD 4870",
    );
  });

  it("groups offers into open, in progress and closed", () => {
    const offer = (status: string, lead_status: string) =>
      ({ lead: { status, lead_status } }) as Parameters<typeof groupOffers>[0][number];
    const { open, working, closed } = groupOffers([
      offer("MATCHED", "OPEN"),
      offer("VIEWED", "FILLED"),
      offer("CLAIMED", "FILLED"),
      offer("QUOTED", "OPEN"),
      offer("WON", "FILLED"),
      offer("DECLINED", "OPEN"),
    ]);
    expect(open).toHaveLength(1);
    expect(working).toHaveLength(2);
    expect(closed).toHaveLength(3);
  });
});
