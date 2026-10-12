import type { OfficialForm } from "@approvalready/shared-types";
import { describe, expect, it } from "vitest";

import { formLabel, formsMentioned, splitByForms } from "./officialForms";

function form(overrides: Partial<OfficialForm>): OfficialForm {
  return {
    id: "rta-form-1",
    code: "Form 1",
    name: "Example",
    publisher: "RTA",
    url: "https://example.gov.au/form-1",
    mentions: [],
    verticals: [],
    note: null,
    ...overrides,
  };
}

describe("splitByForms", () => {
  const one = form({});
  const oneA = form({
    id: "rta-form-1a",
    code: "Form 1a",
    url: "https://example.gov.au/1a",
  });
  const da = form({
    id: "da-1",
    code: "DA Form 1",
    mentions: ["DA Form 1"],
    url: "https://x/da",
  });

  it("links each mention to its own form, never inside a longer number", () => {
    const pieces = splitByForms("Use Form 1a, then Form 1, not Form 18.", [one, oneA]);
    expect(pieces).toEqual([
      "Use ",
      { text: "Form 1a", form: oneA },
      ", then ",
      { text: "Form 1", form: one },
      ", not Form 18.",
    ]);
  });

  it("prefers the longest phrase at the same place", () => {
    const pieces = splitByForms("Lodge DA Form 1 now", [one, da]);
    expect(pieces).toEqual(["Lodge ", { text: "DA Form 1", form: da }, " now"]);
  });

  it("leaves text alone when there are no forms", () => {
    expect(splitByForms("Form 1", [])).toEqual(["Form 1"]);
  });

  it("lists the forms texts mention once each", () => {
    expect(formsMentioned(["Form 1a and Form 1", "Form 1 again", null], [one, oneA])).toEqual([
      oneA,
      one,
    ]);
  });

  it("names a form by number and name", () => {
    expect(formLabel(form({ name: "Bond lodgement", code: "Form 2" }))).toBe(
      "Form 2 Bond lodgement",
    );
    expect(formLabel(form({ name: "Form 2 Bond lodgement", code: "Form 2" }))).toBe(
      "Form 2 Bond lodgement",
    );
  });
});
