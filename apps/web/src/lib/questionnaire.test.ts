import type { QuestionOut, QuestionnaireOut } from "@approvalready/shared-types";

import {
  cleanAnswer,
  displayAnswer,
  formatDollars,
  parseDecimal,
  parseDollars,
  parseText,
  parseWholeNumber,
  textFor,
  visibility,
} from "./questionnaire";

function q(key: string, extra: Partial<QuestionOut> = {}): QuestionOut {
  return {
    key,
    type: "TEXT",
    label: key,
    help_text: null,
    required: false,
    options: [],
    validation: {},
    visible_when: null,
    ...extra,
  };
}

const QUESTIONNAIRE: QuestionnaireOut = {
  key: "t.t",
  vertical: "PLANNING",
  version: 1,
  title: "T",
  description: null,
  sections: [
    {
      title: "One",
      questions: [
        q("site", { type: "ADDRESS", required: true }),
        q("kind", {
          type: "SELECT",
          required: true,
          options: [
            { value: "sub", label: "Subdivide" },
            { value: "ext", label: "Extend" },
          ],
        }),
        q("lots", {
          type: "NUMBER",
          required: true,
          visible_when: { fact: "kind", op: "equals", value: "sub" },
        }),
        q("big", {
          type: "BOOLEAN",
          visible_when: { fact: "lots", op: "greater_than", value: 10 },
        }),
        q("qld", { visible_when: { fact: "site.state", op: "equals", value: "QLD" } }),
        q("area", { type: "DECIMAL" }),
        q("area_note", { visible_when: { fact: "area", op: "greater_equal", value: 600 } }),
      ],
    },
  ],
};

describe("visibility", () => {
  it("shows only unconditional questions at the start and lists what's required", () => {
    const { visible, missingRequired } = visibility(QUESTIONNAIRE, {});
    expect([...visible]).toEqual(["site", "kind", "area"]);
    expect(missingRequired).toEqual(["site", "kind"]);
  });

  it("follows chained branches in order", () => {
    const answers = { kind: "sub", lots: 12 };
    expect([...visibility(QUESTIONNAIRE, answers).visible]).toContain("big");
    // The chain breaks when the controlling answer changes.
    expect([...visibility(QUESTIONNAIRE, { ...answers, kind: "ext" }).visible]).not.toContain("big");
  });

  it("exposes address fields and compares decimals stored as strings", () => {
    const answers = { site: { line1: "1 A St", suburb: "Cairns", state: "QLD", postcode: "4870" }, area: "607.5" };
    const { visible } = visibility(QUESTIONNAIRE, answers);
    expect(visible.has("qld")).toBe(true);
    expect(visible.has("area_note")).toBe(true);
    expect(visibility(QUESTIONNAIRE, { area: "599.99" }).visible.has("area_note")).toBe(false);
  });
});

describe("typed input", () => {
  it("parses whole numbers, decimals and dollars", () => {
    expect(parseWholeNumber("1,200")).toEqual({ value: 1200 });
    expect(parseWholeNumber("1.5")).toHaveProperty("error");
    expect(parseWholeNumber(" ")).toEqual({ value: null });
    expect(parseDecimal("607.50")).toEqual({ value: "607.50" });
    expect(parseDecimal("abc")).toHaveProperty("error");
    expect(parseDollars("$1,500.5")).toEqual({ value: 150050 });
    expect(parseDollars("0.07")).toEqual({ value: 7 });
    expect(parseDollars("1.234")).toHaveProperty("error");
    expect(formatDollars(150050)).toBe("1500.50");
    expect(formatDollars(150000)).toBe("1500");
  });

  it("describes answers for review", () => {
    const kind = QUESTIONNAIRE.sections[0]!.questions[1]!;
    expect(displayAnswer(kind, "sub")).toBe("Subdivide");
    expect(displayAnswer(kind, null)).toBe("Not answered");
    expect(displayAnswer(q("c", { type: "CURRENCY" }), 150050)).toBe("$1,500.50");
    expect(displayAnswer(q("b", { type: "BOOLEAN" }), false)).toBe("No");
  });
});

describe("cleanAnswer", () => {
  it("turns blanks into null so the answer is cleared", () => {
    const text = q("t");
    expect(cleanAnswer(text, "  ")).toBeNull();
    expect(cleanAnswer(q("m", { type: "MULTISELECT" }), [])).toBeNull();
    expect(cleanAnswer(q("a", { type: "ADDRESS" }), { line1: "", state: "" })).toBeNull();
    expect(cleanAnswer(q("a", { type: "ADDRESS" }), { line1: "1 A St", line2: "" })).toEqual({
      line1: "1 A St",
    });
    expect(cleanAnswer(q("b", { type: "BOOLEAN" }), false)).toBe(false);
  });

  it("round-trips number text", () => {
    const money = q("c", { type: "CURRENCY" });
    expect(textFor(money, 150050)).toBe("1500.50");
    expect(parseText(money, textFor(money, 150050)!)).toEqual({ value: 150050 });
    expect(textFor(q("t"), "x")).toBeUndefined();
  });
});
