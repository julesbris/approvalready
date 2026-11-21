/** RemoteSafe: labels and form helpers (pure, unit tested). */

export const STATUS_LABELS: Record<string, string> = {
  DRAFT: "Draft",
  SUBMITTED: "Waiting for approval",
  CHANGES_REQUESTED: "Changes requested",
  APPROVED: "Approved",
  ACTIVE: "Underway",
  OVERDUE: "Overdue",
  ESCALATED: "Escalated",
  COMPLETED: "Completed",
  CANCELLED: "Cancelled",
};

export const RATING_LABELS: Record<string, string> = {
  LOW: "Low",
  MODERATE: "Moderate",
  HIGH: "High",
  CRITICAL: "Critical",
};

export const ROLE_LABELS: Record<string, string> = {
  WORKER: "Worker",
  SUPERVISOR: "Supervisor",
  MONITOR: "Journey monitor",
  WHS_ADMIN: "WHS administrator",
};

export const REMOTENESS_LABELS: Record<string, string> = {
  UNKNOWN: "Not sure",
  NOT_REMOTE: "Not remote (towns and highways)",
  REMOTE: "Remote",
  VERY_REMOTE: "Very remote (e.g. Cape York, outback)",
};

export const SURFACE_LABELS: Record<string, string> = {
  UNKNOWN: "Not sure",
  SEALED: "Sealed",
  MIXED: "Mixed",
  UNSEALED: "Unsealed (gravel or dirt)",
};

export const COVERAGE_LABELS: Record<string, string> = {
  UNKNOWN: "Not sure",
  GOOD: "Good",
  PATCHY: "Patchy",
  NONE: "None",
};

export const CLOSURE_LABELS: Record<string, string> = {
  NOT_CHECKED: "Not checked yet",
  NONE_KNOWN: "Checked: none known",
  RESTRICTED: "Restriction in place",
  CONFIRMED_CLOSED: "Confirmed closed",
};

export const CHECKIN_METHOD_LABELS: Record<string, string> = {
  PHONE_CALL: "Phone call",
  SMS: "Text message",
  SATELLITE_MESSAGE: "Satellite message",
  SATELLITE_CALL: "Satellite phone call",
  UHF: "UHF radio",
  APP: "RemoteSafe app",
};

export const CONTROL_GROUP_LABELS: Record<string, string> = {
  VEHICLE: "Vehicle readiness",
  COMMUNICATIONS: "Communications",
  WORKER: "Worker readiness",
};

export const ACTION_LABELS: Record<string, string> = {
  submit: "Submit for approval",
  approve: "Approve",
  request_changes: "Ask for changes",
  commence: "Start the journey",
  complete: "Mark completed",
  escalate: "Escalate",
  cancel: "Cancel journey",
  archive: "Archive record",
};

/** Actions that need a note (the API refuses them without one). */
export const NOTE_REQUIRED = new Set(["request_changes", "escalate"]);

export function label(map: Record<string, string>, key: string | null | undefined): string {
  if (!key) return "Not assessed";
  return map[key] ?? key;
}

export function ratingClass(rating: string | null | undefined): string {
  return `rating rating-${(rating ?? "none").toLowerCase()}`;
}

/** "2026-11-24T06:00" for a datetime-local input, from the API's local label's UTC value. */
export function toLocalInput(utc: string, timeZone: string): string {
  const parts = new Intl.DateTimeFormat("en-AU", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(utc));
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")}T${get("hour")}:${get("minute")}`;
}

export type ContactRow = { name: string; relationship: string; phone: string };

/** Contacts typed one per line: "Name, relationship, phone" (relationship optional). */
export function parseContacts(text: string): ContactRow[] | { error: string } {
  const rows: ContactRow[] = [];
  for (const [i, raw] of text.split("\n").entries()) {
    const line = raw.trim();
    if (!line) continue;
    const parts = line.split(",").map((p) => p.trim());
    if (parts.length < 2 || !parts[0] || !parts[parts.length - 1]) {
      return { error: `Contact line ${i + 1}: write "Name, relationship, phone".` };
    }
    const phone = parts[parts.length - 1] ?? "";
    if (!/[0-9]{3,}/.test(phone.replace(/\s/g, ""))) {
      return { error: `Contact line ${i + 1}: the last part should be a phone number.` };
    }
    rows.push({
      name: parts[0] ?? "",
      relationship: parts.length > 2 ? parts.slice(1, -1).join(", ") : "",
      phone,
    });
  }
  return rows;
}

export function formatContacts(
  contacts: { name: string; relationship?: string | null; phone: string }[],
): string {
  return contacts
    .map((c) => [c.name, c.relationship, c.phone].filter(Boolean).join(", "))
    .join("\n");
}

/** Planned check-ins every ``minutes`` between departure and arrival (local wall times). */
export function checkinTimes(departs: string, arrives: string, minutes: number): string[] {
  const start = Date.parse(`${departs}:00Z`);
  const end = Date.parse(`${arrives}:00Z`);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start || minutes < 15) return [];
  const out: string[] = [];
  for (let t = start + minutes * 60_000; t < end && out.length < 99; t += minutes * 60_000) {
    out.push(new Date(t).toISOString().slice(0, 16));
  }
  out.push(new Date(end).toISOString().slice(0, 16));
  return out;
}
