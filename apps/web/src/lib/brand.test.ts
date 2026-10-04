import { CONFIDENCE_LEVELS, VERTICALS } from "@approvalready/shared-types";

import { defaultBrand, resolveBrand } from "./brand";

describe("brand configuration", () => {
  it("covers every vertical exactly once", () => {
    expect(defaultBrand.products.map((p) => p.key).sort()).toEqual([...VERTICALS].sort());
  });

  it("falls back to the default brand for unknown hosts", () => {
    expect(resolveBrand("unknown.example").key).toBe("approvalready");
  });

  it("exposes the four confidence levels", () => {
    expect(CONFIDENCE_LEVELS).toEqual(["VERIFIED", "LIKELY", "REVIEW_REQUIRED", "UNKNOWN"]);
  });
});
