import type { CouncilOut } from "@approvalready/shared-types";

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
