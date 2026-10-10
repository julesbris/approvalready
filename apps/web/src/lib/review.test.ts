import type { FindingOut, OverrideOut, RefundOut, ReviewOut } from "@approvalready/shared-types";

import { applyOverrides, cancelQuestion, isOpen, refundLine, reviewerName } from "./review";

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

describe("refunds", () => {
  const paid = {
    id: "p",
    status: "PAID",
    amount_cents: 24900,
    currency: "AUD",
    paid_at: "2026-10-10T00:00:00Z",
    refunded_cents: 0,
    refunds: [],
  };
  const review = (status: string, cancel_refund_cents: number, payment: unknown = paid) =>
    ({ status, cancel_refund_cents, payment }) as unknown as ReviewOut;

  it("tells the customer whether cancelling refunds them", () => {
    expect(cancelQuestion(review("ASSIGNED", 24900))).toContain("we'll refund $249.00");
    expect(cancelQuestion(review("IN_REVIEW", 0))).toContain("isn't refunded automatically");
    expect(cancelQuestion(review("REVIEW_REQUESTED", 0, null))).toBe("Cancel this review?");
    expect(
      cancelQuestion(review("PAYMENT_PENDING", 0, { ...paid, paid_at: null, status: "PENDING" })),
    ).toBe("Cancel this review?");
  });

  it("describes each refund in plain words", () => {
    const refund = (status: string) =>
      ({ amount_cents: 15000, currency: "AUD", status }) as unknown as RefundOut;
    const done = "Refunded $150.00. Most banks show it within 5 to 10 business days.";
    expect(refundLine(refund("SUCCEEDED"))).toBe(done);
    expect(refundLine(refund("SUBMITTED"))).toBe(done);
    expect(refundLine(refund("PENDING"))).toBe("Refund of $150.00: being sent.");
    expect(refundLine(refund("FAILED"))).toContain("delayed");
  });
});
