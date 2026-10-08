import type { FindingOut } from "@approvalready/shared-types";

import { type TraceNode, describeLeaf, formatValue, groupFindings, leaves } from "./assessment";

const LABELS = { "planning.floor_area_m2": "Floor area (m²)" };

describe("assessment presentation", () => {
  it("describes a checked condition with the customer's answer", () => {
    const leaf: TraceNode = {
      kind: "leaf",
      fact: "planning.floor_area_m2",
      op: "greater_than",
      value: 80,
      actual: "92.5",
      missing: false,
      result: "TRUE",
    };
    expect(describeLeaf(leaf, LABELS)).toBe("Floor area (m²): 92.5 (checked: is more than 80)");
    expect(describeLeaf({ ...leaf, actual: null, missing: true, result: "UNKNOWN" }, LABELS)).toBe(
      "Floor area (m²): not answered (needed to check whether it is more than 80)",
    );
    expect(describeLeaf({ ...leaf, fact: "x.y", op: "exists", value: undefined }, LABELS)).toBe(
      "x.y: 92.5 (checked: is provided)",
    );
  });

  it("formats stored values", () => {
    expect(formatValue({ $decimal: "812.25" })).toBe("812.25");
    expect(formatValue(true)).toBe("yes");
    expect(formatValue(["secondary_dwelling", "flooding"])).toBe("secondary dwelling, flooding");
    expect(formatValue(null)).toBe("not answered");
  });

  it("flattens traces to their leaves", () => {
    const trace: TraceNode = {
      kind: "all",
      result: "FALSE",
      children: [
        { kind: "leaf", fact: "a", op: "exists", result: "TRUE" },
        {
          kind: "not",
          result: "FALSE",
          children: [{ kind: "leaf", fact: "b", op: "exists", result: "TRUE" }],
        },
      ],
    };
    expect(leaves(trace).map((l) => l.fact)).toEqual(["a", "b"]);
  });

  it("puts findings to act on first and leaves out results without an outcome", () => {
    const base = {
      result: "MATCH",
      outcome_type: "APPROVAL_REQUIRED",
    } as FindingOut;
    const findings = [
      { ...base, id: "info", outcome_type: "INFO" },
      { ...base, id: "act" },
      { ...base, id: "unknown", result: "UNKNOWN", outcome_type: null },
      { ...base, id: "silent", result: "NO_MATCH", outcome_type: null },
    ] as FindingOut[];
    const grouped = groupFindings(findings);
    expect(grouped.action.map((f) => f.id)).toEqual(["act"]);
    expect(grouped.missing.map((f) => f.id)).toEqual(["unknown"]);
    expect(grouped.other.map((f) => f.id)).toEqual(["info"]);
  });
});
