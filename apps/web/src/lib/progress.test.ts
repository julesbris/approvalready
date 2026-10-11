import type { QuietProjectOut } from "@approvalready/shared-types";
import { describe, expect, it } from "vitest";

import { daysSince, openSummary, quietDays } from "./progress";

const base = {
  documents_missing: 0,
  open_tasks: 0,
  checklist_open: 0,
} as QuietProjectOut;

describe("stuck projects", () => {
  it("only accepts the offered filters", () => {
    expect(quietDays("7")).toBe(7);
    expect(quietDays("5")).toBe(1);
    expect(quietDays(undefined)).toBe(1);
  });

  it("summarises what is still open", () => {
    expect(openSummary(base)).toBe("None");
    expect(openSummary({ ...base, documents_missing: 2, open_tasks: 1 })).toBe(
      "2 documents, 1 task",
    );
  });

  it("counts whole days of quiet", () => {
    const now = new Date("2026-10-11T10:00:00Z");
    expect(daysSince("2026-10-08T09:00:00Z", now)).toBe(3);
    expect(daysSince("2026-10-11T11:00:00Z", now)).toBe(0);
  });
});
