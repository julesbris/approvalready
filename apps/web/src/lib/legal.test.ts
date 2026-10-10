import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { POLICY_VERSIONS, policyDate, requestReference } from "@/lib/legal";

describe("legal", () => {
  it("keeps the policy versions in step with the API", () => {
    const file = join(__dirname, "../../../api/app/modules/privacy/policies.json");
    const api = JSON.parse(readFileSync(file, "utf-8")) as Record<string, { version: string }>;
    expect(Object.keys(api).sort()).toEqual(Object.keys(POLICY_VERSIONS).sort());
    for (const [key, version] of Object.entries(POLICY_VERSIONS)) {
      expect(api[key]?.version).toBe(version);
    }
  });

  it("formats versions and references", () => {
    expect(policyDate("2026-10-10")).toBe("10 October 2026");
    expect(requestReference("0199d2b4-1c2e-7a3b-9f00-12ab34cd56ef")).toBe("34CD56EF");
  });
});
