import {
  checkinTimes,
  formatContacts,
  label,
  parseContacts,
  ratingClass,
  STATUS_LABELS,
  toLocalInput,
} from "./remotesafe";

describe("remotesafe helpers", () => {
  it("parses emergency contacts one per line", () => {
    expect(parseContacts("Depot, base, 07 4000 0000\n\nArea manager, 0411 111 111")).toEqual([
      { name: "Depot", relationship: "base", phone: "07 4000 0000" },
      { name: "Area manager", relationship: "", phone: "0411 111 111" },
    ]);
    expect(parseContacts("Just a name")).toEqual({
      error: 'Contact line 1: write "Name, relationship, phone".',
    });
    expect(parseContacts("Depot, base")).toEqual({
      error: "Contact line 1: the last part should be a phone number.",
    });
  });

  it("round-trips contacts", () => {
    const text = "Depot, base, 07 4000 0000\nArea manager, 0411 111 111";
    const parsed = parseContacts(text);
    expect(Array.isArray(parsed) && formatContacts(parsed)).toBe(text);
  });

  it("plans check-ins on the interval and at arrival", () => {
    expect(checkinTimes("2026-11-24T06:00", "2026-11-24T13:00", 120)).toEqual([
      "2026-11-24T08:00",
      "2026-11-24T10:00",
      "2026-11-24T12:00",
      "2026-11-24T13:00",
    ]);
    expect(checkinTimes("2026-11-24T06:00", "2026-11-24T05:00", 120)).toEqual([]);
  });

  it("shows UTC as wall time in each Australian zone", () => {
    // 20:00 UTC on 23 Nov is 06:00 in Brisbane (no daylight saving) and 07:00 in Sydney.
    expect(toLocalInput("2026-11-23T20:00:00Z", "Australia/Brisbane")).toBe("2026-11-24T06:00");
    expect(toLocalInput("2026-11-23T20:00:00Z", "Australia/Sydney")).toBe("2026-11-24T07:00");
  });

  it("labels statuses and ratings", () => {
    expect(label(STATUS_LABELS, "SUBMITTED")).toBe("Waiting for approval");
    expect(label(STATUS_LABELS, null)).toBe("Not assessed");
    expect(ratingClass("CRITICAL")).toBe("rating rating-critical");
  });
});
