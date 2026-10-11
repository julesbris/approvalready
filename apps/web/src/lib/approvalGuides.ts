import type { AssessmentOut } from "@approvalready/shared-types";

/** A phone number as a tel: link target ("07 4044 3044" to "+61740443044"). */
export function phoneHref(phone: string): string | null {
  const digits = phone.replace(/[^\d+]/g, "");
  if (digits.startsWith("+")) return `tel:${digits}`;
  if (/^0\d{9}$/.test(digits)) return `tel:+61${digits.slice(1)}`;
  if (/^1[38]00\d{6}$/.test(digits) || /^13\d{4}$/.test(digits)) return `tel:${digits}`;
  return null;
}

/**
 * The approval kinds an assessment says apply (required, likely or may apply), each once, so
 * the page can ask for their step-by-step guides. Approvals it found don't apply are left out.
 */
export function guideKinds(assessment: AssessmentOut): string[] {
  const kinds = [
    ...assessment.approval_requirements.map((a) => a.kind),
    ...assessment.approval_map.filter((e) => e.certainty !== "NOT_IDENTIFIED").map((e) => e.kind),
  ];
  return [...new Set(kinds)];
}

/** The query string for `/guidance/approvals`: one `kind` per approval, and the product. */
export function guideQuery(kinds: string[], vertical?: string): string {
  const params = new URLSearchParams(kinds.map((k) => ["kind", k]));
  if (vertical) params.set("vertical", vertical);
  return params.toString();
}
