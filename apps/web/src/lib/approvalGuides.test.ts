import type { AssessmentOut } from "@approvalready/shared-types";
import { describe, expect, it } from "vitest";

import { guideKinds, guideQuery, phoneHref } from "./approvalGuides";

describe("approval guides", () => {
  it("asks for each approval found once, leaving out ones that don't apply", () => {
    const assessment = {
      approval_requirements: [{ kind: "ABN_REGISTRATION" }, { kind: "FOOD_BUSINESS_LICENCE" }],
      approval_map: [
        { kind: "ABN_REGISTRATION", certainty: "REQUIRED" },
        { kind: "LIQUOR_LICENCE", certainty: "MAY_APPLY" },
        { kind: "GST_REGISTRATION", certainty: "NOT_IDENTIFIED" },
      ],
    } as unknown as AssessmentOut;
    const kinds = guideKinds(assessment);
    expect(kinds).toEqual(["ABN_REGISTRATION", "FOOD_BUSINESS_LICENCE", "LIQUOR_LICENCE"]);
    expect(guideQuery(kinds.slice(0, 2), "BUSINESS")).toBe(
      "kind=ABN_REGISTRATION&kind=FOOD_BUSINESS_LICENCE&vertical=BUSINESS",
    );
  });

  it("turns Australian phone numbers into tel: links", () => {
    expect(phoneHref("13 23 80")).toBe("tel:132380");
    expect(phoneHref("1300 69 22 47")).toBe("tel:1300692247");
    expect(phoneHref("(07) 4044 3237")).toBe("tel:+61740443237");
    expect(phoneHref("ask at the counter")).toBeNull();
  });
});
