/** Parse JSON typed into an admin form; returns an error message instead of throwing. */
export function parseJson(
  raw: string,
  what: string,
  { optional = false } = {},
): { ok: true; value: unknown } | { ok: false; message: string } {
  if (raw.trim() === "") {
    return optional ? { ok: true, value: null } : { ok: false, message: `Enter the ${what}.` };
  }
  try {
    return { ok: true, value: JSON.parse(raw) as unknown };
  } catch {
    return { ok: false, message: `The ${what} is not valid JSON.` };
  }
}

export function prettyJson(value: unknown): string {
  return value === null || value === undefined ? "" : JSON.stringify(value, null, 2);
}

export const CONDITION_HELP =
  'A condition is JSON, e.g. {"all": [{"fact": "planning.floor_area_m2", "op": "greater_than", ' +
  '"value": 80}]}. Combine with "all", "any" and "not".';

export const PAYLOAD_HELP =
  'e.g. {"approval": {"kind": "BUILDING_WORKS", "authority": "A building certifier"}, ' +
  '"evidence": [{"kind": "SITE_PLAN", "title": "Site plan"}], ' +
  '"referral_categories": ["town_planner"], "task": "Engage a certifier"}. ' +
  "An approval is never more certain than the outcome type allows.";
