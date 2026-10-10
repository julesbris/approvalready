import { describe, expect, it } from "vitest";

import { duration, monthLabel, parsePeriod, percent } from "./analytics";

describe("analytics helpers", () => {
  it("reads the period from the address", () => {
    expect(parsePeriod("3")).toBe(3);
    expect(parsePeriod("12")).toBe(12);
    expect(parsePeriod("4")).toBe(6);
    expect(parsePeriod(undefined)).toBe(6);
  });

  it("shows rates as whole percentages", () => {
    expect(percent(0.5)).toBe("50%");
    expect(percent(0.333)).toBe("33%");
    expect(percent(0)).toBe("0%");
    expect(percent(null)).toBe("–");
  });

  it("shows response times in minutes, hours or days", () => {
    expect(duration(0.25)).toBe("15 min");
    expect(duration(0.001)).toBe("1 min");
    expect(duration(1)).toBe("1 hour");
    expect(duration(5.54)).toBe("5.5 hours");
    expect(duration(72)).toBe("3 days");
    expect(duration(null)).toBe("–");
  });

  it("names months", () => {
    expect(monthLabel("2026-10")).toBe("Oct 2026");
    expect(monthLabel("2025-01")).toBe("Jan 2025");
  });
});
