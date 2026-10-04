import { readFileSync } from "node:fs";
import path from "node:path";

import { type Condition, type Facts, type Tri, evaluate } from "./conditions";

type Vector = { name: string; condition: Condition; facts: Facts; expected: Tri };

// The same vectors run against the API's evaluator (apps/api/tests/test_conditions.py).
const VECTORS = JSON.parse(
  readFileSync(
    path.resolve(import.meta.dirname, "../../../../tests/fixtures/condition_vectors.json"),
    "utf8",
  ),
) as Vector[];

describe("condition evaluator", () => {
  it("has the shared vectors", () => {
    expect(VECTORS.length).toBeGreaterThan(40);
  });

  it.each(VECTORS.map((v) => [v.name, v] as const))("%s", (_name, vector) => {
    expect(evaluate(vector.condition, vector.facts)).toBe(vector.expected);
  });

  it("rejects impossible dates as dates", () => {
    expect(evaluate({ fact: "d", op: "greater_than", value: "2026-01-01" }, { d: "2026-02-30" })).toBe(
      "UNKNOWN",
    );
  });
});
