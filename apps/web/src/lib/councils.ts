import type { CouncilOut } from "@approvalready/shared-types";

import { formatDate } from "@/lib/questionnaire";

/** The Australian financial year a date falls in, as councils label fee schedules: "2026-27". */
export function financialYear(on: Date = new Date()): string {
  const start = on.getMonth() >= 6 ? on.getFullYear() : on.getFullYear() - 1;
  return `${start}-${String((start + 1) % 100).padStart(2, "0")}`;
}

/** True when a fee schedule's year is older than the current financial year. */
export function feesMayBeOutOfDate(feeYear: string | null | undefined, on: Date = new Date()) {
  return Boolean(feeYear) && (feeYear as string) < financialYear(on);
}

export const LODGEMENT_LABELS: Record<CouncilOut["lodgement"][number]["method"], string> = {
  ONLINE: "Online",
  EMAIL: "Email",
  POST: "Post",
  IN_PERSON: "In person",
};

/** A phone number as a tel: link target ("07 4044 3044" to "+61740443044"). */
export function telHref(phone: string): string | null {
  const digits = phone.replace(/[^\d+]/g, "");
  if (digits.startsWith("+")) return `tel:${digits}`;
  if (/^0\d{9}$/.test(digits)) return `tel:+61${digits.slice(1)}`;
  if (/^1[38]00\d{6}$/.test(digits) || /^13\d{4}$/.test(digits)) return `tel:${digits}`;
  return null;
}

/** The council directory key in a planning answer, or null for "another council". */
export function councilKey(answer: unknown): string | null {
  return typeof answer === "string" && answer !== "" && answer !== "other" ? answer : null;
}

/** Where a planning enquiry should go: the planning team's address, else the council's. */
export function enquiryEmail(council: CouncilOut): string | null {
  return council.contact.planning_email ?? council.contact.email ?? null;
}

const DEVELOPMENT_TYPES: Record<string, string> = {
  secondary_dwelling: "a secondary dwelling (granny flat)",
  new_dwelling: "a new house",
  extension: "an extension to the house",
  subdivision: "a subdivision",
  change_of_use: "a change of use",
};

const CONSTRAINTS: Record<string, string> = {
  heritage: "heritage",
  flooding: "flooding",
  bushfire: "bushfire",
  vegetation: "protected vegetation",
  easement: "an easement",
  steep_slope: "a steep slope",
};

function text(value: unknown): string | null {
  if (typeof value === "number") return String(value);
  return typeof value === "string" && value.trim() !== "" ? value.trim() : null;
}

function addressText(value: unknown): string | null {
  if (typeof value === "string") return text(value);
  if (!value || typeof value !== "object") return null;
  const a = value as Record<string, unknown>;
  const place = [a.suburb, a.state, a.postcode].map(text).filter(Boolean).join(" ");
  return [text(a.line1), text(a.line2), place || null].filter(Boolean).join(", ") || null;
}

export type CouncilEnquiry = { subject: string; body: string };

/**
 * A pre-lodgement enquiry to the council's planning team, filled in from the planning
 * answers (or an assessment's facts, which use the same keys) so the person only adds
 * their name and phone number.
 */
export function councilEnquiry(
  council: CouncilOut,
  answers: Record<string, unknown> = {},
): CouncilEnquiry {
  const address = addressText(answers["property.address"]);
  const lotPlan = text(answers["property.lot_plan"]);
  const type = text(answers["planning.development_type"]);
  const project = (type && DEVELOPMENT_TYPES[type]) || "a development";
  const where = address ? ` at ${address}` : "";

  const details: string[] = [];
  if (address) details.push(`Site: ${address}`);
  if (lotPlan) details.push(`Lot and plan: ${lotPlan}`);
  const area = text(answers["property.land_area_m2"]);
  if (area) details.push(`Land area: about ${area} m²`);
  if (typeof answers["property.has_existing_dwelling"] === "boolean") {
    details.push(
      `Existing house on the land: ${answers["property.has_existing_dwelling"] ? "yes" : "no"}`,
    );
  }
  const bedrooms = text(answers["planning.secondary_dwelling_bedrooms"]);
  if (bedrooms) details.push(`Bedrooms: ${bedrooms}`);
  const floor = text(answers["planning.secondary_dwelling_floor_area_m2"]);
  if (floor) details.push(`Floor area: about ${floor} m²`);
  const storeys = text(answers["planning.storeys"]);
  if (storeys) details.push(`Storeys: ${storeys}`);
  const lots = text(answers["planning.proposed_lots"]);
  if (lots) details.push(`Lots after subdividing: ${lots}`);
  const smallest = text(answers["planning.smallest_lot_m2"]);
  if (smallest) details.push(`Smallest new lot: about ${smallest} m²`);
  const current = text(answers["planning.current_use"]);
  if (current) details.push(`Current use: ${current}`);
  const proposed = text(answers["planning.proposed_use"]);
  if (proposed) details.push(`Proposed use: ${proposed}`);
  const described = text(answers["planning.other_description"]);
  if (described) details.push(`What I'm planning: ${described}`);
  const constraints = answers["planning.known_constraints"];
  if (Array.isArray(constraints) && constraints.length > 0) {
    const named = constraints.map((c) => CONSTRAINTS[String(c)] ?? String(c));
    details.push(`Site constraints I know of: ${named.join(", ")}`);
  }
  const start = text(answers["planning.target_start_date"]);
  if (start) details.push(`Hoping to start: ${formatDate(start)}`);

  const lines = [
    `Hello ${council.name} planning team,`,
    "",
    `I'm planning ${project}${where} and would like to check a few things before I lodge an application.`,
  ];
  if (details.length > 0) lines.push("", "About the project:", ...details.map((d) => `- ${d}`));
  lines.push(
    "",
    "Could you please let me know:",
    "1. Whether this needs a development application, and if so whether it is code or impact assessable for this site.",
    "2. Any overlays or site constraints the application should address.",
    "3. The application fee, and whether you recommend a pre-lodgement meeting (and how to book one).",
    "",
    "Thank you,",
    "[Your name]",
    "[Your phone number]",
  );
  const subject = `Pre-lodgement enquiry: ${project.replace(/^(a|an) /, "")}${where}`;
  return {
    subject: subject.charAt(0).toUpperCase() + subject.slice(1),
    body: lines.join("\n"),
  };
}

/** A mailto: link that opens the enquiry ready to send. */
export function enquiryMailto(to: string, enquiry: CouncilEnquiry): string {
  return `mailto:${to}?subject=${encodeURIComponent(enquiry.subject)}&body=${encodeURIComponent(enquiry.body)}`;
}
