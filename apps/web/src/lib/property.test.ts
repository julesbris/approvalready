import type { ApplicationOut, InspectionItemOut } from "@approvalready/shared-types";
import { describe, expect, it } from "vitest";

import { byRoom, checksSummary, money, vaultCategoryLabel } from "./property";

function item(id: string, room: string, position: number): InspectionItemOut {
  return {
    id,
    room,
    item: `Item ${id}`,
    position,
    condition: null,
    notes: null,
    photo_document_ids: [],
  };
}

describe("money", () => {
  it("drops cents on whole dollars", () => {
    expect(money(65_000_000)).toBe("$650,000");
    expect(money(52_550)).toBe("$525.50");
    expect(money(null)).toBe("");
  });
});

describe("byRoom", () => {
  it("groups items by room in list order", () => {
    const rooms = byRoom([
      item("c", "Kitchen", 3),
      item("a", "Entry", 1),
      item("b", "Kitchen", 2),
    ]);
    expect(rooms.map(([room, items]) => [room, items.map((i) => i.id)])).toEqual([
      ["Entry", ["a"]],
      ["Kitchen", ["b", "c"]],
    ]);
  });
});

describe("checksSummary", () => {
  it("counts the documents provided", () => {
    const application = {
      checks: [
        { key: "identity", label: "Identity", provided: true },
        { key: "income", label: "Income", provided: false },
        { key: "references", label: "References", provided: null },
      ],
    } as ApplicationOut;
    expect(checksSummary(application)).toBe("1 of 3 documents provided");
  });
});

describe("vaultCategoryLabel", () => {
  it("names known categories and passes others through", () => {
    expect(vaultCategoryLabel("POOL_SAFETY")).toBe("Pool safety certificate or notice");
    expect(vaultCategoryLabel("SOMETHING_NEW")).toBe("SOMETHING_NEW");
  });
});
