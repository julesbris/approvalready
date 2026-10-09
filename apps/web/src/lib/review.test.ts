import type { FindingOut, OverrideOut } from "@approvalready/shared-types";

import { applyOverrides, isOpen, reviewerName } from "./review";

const finding = (id: string) =>
  ({ id, outcome_type: "PERMITTED", confidence: "LIKELY" }) as unknown as FindingOut;

const override = (finding_id: string, current: boolean, outcome: string) =>
  ({
    id: `${finding_id}-${outcome}`,
    finding_id,
    current,
    new_outcome_type: outcome,
    new_confidence: "VERIFIED",
    previous_outcome_type: "PERMITTED",
    previous_confidence: "LIKELY",
    reason: "The overlay map shows otherwise.",
  }) as unknown as OverrideOut;

describe("applyOverrides", () => {
  it("applies only each finding's current change and keeps the original", () => {
    const [a, b] = applyOverrides(
      [finding("a"), finding("b")],
      [override("a", false, "PROHIBITED"), override("a", true, "APPLICATION_REQUIRED")],
    );
    if (!a || !b) throw new Error("expected two findings");
    expect(a.outcome_type).toBe("APPLICATION_REQUIRED");
    expect(a.confidence).toBe("VERIFIED");
    expect(a.original).toEqual({ outcome_type: "PERMITTED", confidence: "LIKELY" });
    expect(a.override?.id).toBe("a-APPLICATION_REQUIRED");
    expect(b.outcome_type).toBe("PERMITTED");
    expect(b.override).toBeNull();
  });

  it("leaves findings alone without overrides", () => {
    expect(applyOverrides([finding("a")])[0]?.override).toBeNull();
  });
});

describe("review helpers", () => {
  it("knows which statuses are open", () => {
    expect(isOpen("CHANGES_REQUIRED")).toBe(true);
    expect(isOpen("APPROVED")).toBe(false);
    expect(isOpen("CANCELLED")).toBe(false);
  });

  it("names the reviewer with profession and practice", () => {
    expect(
      reviewerName({
        display_name: "Pat Planner",
        discipline: "TOWN_PLANNER",
        practice_name: "Coastal Planning",
      }),
    ).toBe("Pat Planner, Town planner (Coastal Planning)");
  });
});
