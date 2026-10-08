/**
 * Browser mirror of the API's condition evaluator (apps/api/app/modules/conditions).
 *
 * Used only for instant show/hide while someone fills in a questionnaire. The API
 * re-evaluates every condition on save and its answer is authoritative. Both sides run the
 * shared vectors in tests/fixtures/condition_vectors.json, so the semantics stay identical:
 *
 * - numbers compare numerically; booleans are never numbers;
 * - ordering works on two numbers or two dates, otherwise UNKNOWN;
 * - `equals` on a list fact means "exactly that one value is chosen";
 * - `contains` means list membership, or case-insensitive substring for text;
 * - `in`/`not_in` test a single value against the condition's list;
 * - `exists`/`missing` are the only operators that are definite on a missing fact.
 */

export type Tri = "TRUE" | "FALSE" | "UNKNOWN";

export type Op =
  | "equals"
  | "not_equals"
  | "greater_than"
  | "less_than"
  | "greater_equal"
  | "less_equal"
  | "contains"
  | "not_contains"
  | "in"
  | "not_in"
  | "exists"
  | "missing";

export type Leaf = { fact: string; op: Op; value?: unknown };
export type Condition = { all: Condition[] } | { any: Condition[] } | { not: Condition } | Leaf;

export type Facts = Record<string, unknown>;

const of = (value: boolean): Tri => (value ? "TRUE" : "FALSE");

function negate(result: Tri): Tri {
  if (result === "UNKNOWN") return result;
  return result === "TRUE" ? "FALSE" : "TRUE";
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

const DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

/** Days since the epoch for a real ISO calendar date, else null. */
function asDate(value: unknown): number | null {
  if (typeof value !== "string") return null;
  const match = DATE.exec(value);
  if (!match) return null;
  const [y, m, d] = [Number(match[1]), Number(match[2]), Number(match[3])];
  const time = Date.UTC(y, m - 1, d);
  const check = new Date(time);
  if (y < 1 || check.getUTCFullYear() !== y || check.getUTCMonth() !== m - 1 || check.getUTCDate() !== d) {
    return null;
  }
  return time / 86_400_000;
}

function same(a: unknown, b: unknown): boolean {
  const na = asNumber(a);
  const nb = asNumber(b);
  if (na !== null || nb !== null) return na !== null && nb !== null && na === nb;
  const da = asDate(a);
  const db = asDate(b);
  if (da !== null && db !== null) return da === db;
  if (typeof a === "boolean" || typeof b === "boolean") return a === b;
  return typeof a === "string" && typeof b === "string" && a === b;
}

function equals(fact: unknown, value: unknown): Tri {
  if (Array.isArray(fact)) return of(fact.length === 1 && same(fact[0], value));
  return of(same(fact, value));
}

function order(fact: unknown, value: unknown, test: (c: number) => boolean): Tri {
  const pairs: [number | null, number | null][] = [
    [asNumber(fact), asNumber(value)],
    [asDate(fact), asDate(value)],
  ];
  for (const [a, b] of pairs) {
    if (a !== null && b !== null) return of(test(Math.sign(a - b)));
  }
  return "UNKNOWN";
}

function contains(fact: unknown, value: unknown): Tri {
  if (Array.isArray(fact)) return of(fact.some((item) => same(item, value)));
  if (typeof fact === "string" && typeof value === "string") {
    return of(fact.toLowerCase().includes(value.toLowerCase()));
  }
  return "UNKNOWN";
}

function inList(fact: unknown, value: unknown): Tri {
  if (Array.isArray(fact) || !Array.isArray(value)) return "UNKNOWN";
  return of(value.some((v) => same(fact, v)));
}

function isMissing(value: unknown): boolean {
  return (
    value === undefined ||
    value === null ||
    ((typeof value === "string" || Array.isArray(value)) && value.length === 0)
  );
}

const OPERATORS: Record<Exclude<Op, "exists" | "missing">, (f: unknown, v: unknown) => Tri> = {
  equals,
  not_equals: (f, v) => negate(equals(f, v)),
  greater_than: (f, v) => order(f, v, (c) => c > 0),
  less_than: (f, v) => order(f, v, (c) => c < 0),
  greater_equal: (f, v) => order(f, v, (c) => c >= 0),
  less_equal: (f, v) => order(f, v, (c) => c <= 0),
  contains,
  not_contains: (f, v) => negate(contains(f, v)),
  in: inList,
  not_in: (f, v) => negate(inList(f, v)),
};

export function evaluate(node: Condition, facts: Facts): Tri {
  if ("all" in node) {
    const results = node.all.map((child) => evaluate(child, facts));
    if (results.includes("FALSE")) return "FALSE";
    return results.includes("UNKNOWN") ? "UNKNOWN" : "TRUE";
  }
  if ("any" in node) {
    const results = node.any.map((child) => evaluate(child, facts));
    if (results.includes("TRUE")) return "TRUE";
    return results.includes("UNKNOWN") ? "UNKNOWN" : "FALSE";
  }
  if ("not" in node) return negate(evaluate(node.not, facts));

  const fact = Object.hasOwn(facts, node.fact) ? facts[node.fact] : undefined;
  if (node.op === "exists") return of(!isMissing(fact));
  if (node.op === "missing") return of(isMissing(fact));
  if (isMissing(fact)) return "UNKNOWN";
  const operator = OPERATORS[node.op];
  return operator ? operator(fact, node.value) : "UNKNOWN";
}
