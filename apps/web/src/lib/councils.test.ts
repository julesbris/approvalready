import { describe, expect, it } from "vitest";

import { councilKey, feesMayBeOutOfDate, financialYear, telHref } from "@/lib/councils";

describe("financialYear", () => {
  it("starts in July", () => {
    expect(financialYear(new Date(2026, 9, 11))).toBe("2026-27");
    expect(financialYear(new Date(2026, 5, 30))).toBe("2025-26");
    expect(financialYear(new Date(2099, 6, 1))).toBe("2099-00");
  });
});

describe("feesMayBeOutOfDate", () => {
  it("flags schedules from an earlier financial year", () => {
    const on = new Date(2026, 9, 11);
    expect(feesMayBeOutOfDate("2025-26", on)).toBe(true);
    expect(feesMayBeOutOfDate("2026-27", on)).toBe(false);
    expect(feesMayBeOutOfDate(null, on)).toBe(false);
  });
});

describe("telHref", () => {
  it("dials Australian numbers", () => {
    expect(telHref("07 4044 3044")).toBe("tel:+61740443044");
    expect(telHref("1300 692 247")).toBe("tel:1300692247");
    expect(telHref("13 74 68")).toBe("tel:137468");
    expect(telHref("ext 12")).toBeNull();
  });
});

describe("councilKey", () => {
  it("ignores blank and other", () => {
    expect(councilKey("cairns")).toBe("cairns");
    expect(councilKey("other")).toBeNull();
    expect(councilKey(undefined)).toBeNull();
  });
});
