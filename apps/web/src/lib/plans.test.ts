import type { PlanStepOut, ProjectPlanOut } from "@approvalready/shared-types";

import { dropStep, dueLabel, putStep, sectionState, todayIso, websiteHref } from "./plans";

function step(id: string, overrides: Partial<PlanStepOut> = {}): PlanStepOut {
  return {
    id,
    section_key: "a",
    position: 1,
    kind: "STEP",
    title: id,
    detail: null,
    timeframe: null,
    cost: null,
    link_url: null,
    link_label: null,
    owner: "You",
    assignee_user_id: null,
    due_on: "2026-10-20",
    status: "OPEN",
    completed_at: null,
    note: null,
    documents: [],
    partner: null,
    editable: false,
    ...overrides,
  };
}

function plan(steps: PlanStepOut[]): ProjectPlanOut {
  return {
    status: "ACTIVE",
    offer: {
      on_sale: false,
      price_cents: null,
      currency: null,
      product_name: "Project plan",
      product_description: "x",
      included_in_membership: false,
      membership_on_sale: false,
    },
    complimentary: true,
    sections: [
      {
        key: "a",
        kind: "APPROVAL",
        title: "A",
        fees: [],
        contacts: [],
        watch_out: [],
        sources: [],
        gaps: [],
        verified: false,
        help: [],
        steps,
        done: 0,
        total: steps.length,
        starts_on: null,
        ends_on: null,
      },
    ],
  };
}

describe("project plans", () => {
  it("works out progress again when a step changes", () => {
    const before = plan([step("one"), step("two", { due_on: "2026-10-01" })]);
    const after = putStep(before, step("one", { status: "DONE" }));
    expect(after.sections[0]!.done).toBe(1);
    expect(after.progress?.percent).toBe(50);
    expect(after.progress?.next_item_id).toBe("two");
    expect(sectionState(after.sections[0]!, "2026-10-11")).toBe("OVERDUE");
    const skipped = putStep(after, step("two", { status: "NOT_APPLICABLE" }));
    expect(skipped.progress?.total).toBe(1);
    expect(sectionState(skipped.sections[0]!, "2026-10-11")).toBe("DONE");
  });

  it("puts new steps in their own part and removes them", () => {
    const added = putStep(plan([step("one")]), step("own1", { section_key: "own" }));
    expect(added.sections.map((s) => s.key)).toEqual(["a", "own"]);
    expect(added.progress?.total).toBe(2);
    expect(dropStep(added, "own1").progress?.total).toBe(1);
  });

  it("says when steps are due in words", () => {
    expect(dueLabel("2026-10-11", "2026-10-11")).toBe("Due today");
    expect(dueLabel("2026-10-12", "2026-10-11")).toBe("Due tomorrow");
    expect(dueLabel("2026-10-14", "2026-10-11")).toBe("Due in 3 days");
    expect(dueLabel("2026-10-09", "2026-10-11")).toBe("2 days overdue");
  });

  it("dates in Brisbane and links websites", () => {
    expect(todayIso(new Date("2026-10-11T15:00:00Z"))).toBe("2026-10-12");
    expect(websiteHref("reef.example.com.au")).toBe("https://reef.example.com.au");
    expect(websiteHref("http://x.au")).toBe("http://x.au");
  });
});
