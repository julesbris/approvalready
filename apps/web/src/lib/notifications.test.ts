import { CATEGORY_LABELS, visiblePreferences } from "./notifications";

const ITEMS = [
  { category: "REMINDERS", channel: "ALL" },
  { category: "SOURCE_REVIEWS", channel: "IN_APP" },
] as const;

describe("visiblePreferences", () => {
  it("shows source reviews to platform staff only", () => {
    expect(visiblePreferences([...ITEMS], false).map((p) => p.category)).toEqual(["REMINDERS"]);
    expect(visiblePreferences([...ITEMS], true)).toHaveLength(2);
  });

  it("labels every category", () => {
    for (const label of Object.values(CATEGORY_LABELS)) expect(label.title).not.toBe("");
  });
});
