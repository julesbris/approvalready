/**
 * Terms of Use and Privacy Policy (Milestone 19).
 *
 * The page text lives in `src/app/terms` and `src/app/privacy`. Each document carries a
 * version (its date); the API's `apps/api/app/modules/privacy/policies.json` must list the
 * same versions (`legal.test.ts` checks). Changing what a policy says means a new version in
 * both places, and every signed-in user is then asked to agree again.
 *
 * The text was drafted for a lawyer to review (see TODO.md backlog): it describes what the
 * platform actually does, but it is not legal advice.
 */

export const POLICY_VERSIONS = {
  terms: "2026-10-10",
  privacy: "2026-10-10",
} as const;

/** Who runs the service and how to reach us. Add the legal entity's name and ABN here. */
export const OPERATOR = {
  name: "ApprovalReady",
  email: "team@approvalready.au",
  state: "Queensland",
} as const;

export const PRIVACY_REQUEST_KINDS = [
  ["ACCESS", "See the personal information you hold about me"],
  ["CORRECTION", "Correct my personal information"],
  ["DELETION", "Delete my personal information"],
  ["COMPLAINT", "Make a privacy complaint"],
  ["OTHER", "Something else about privacy"],
] as const;

export const PRIVACY_REQUEST_LABELS: Record<string, string> = {
  ACCESS: "Access",
  CORRECTION: "Correction",
  DELETION: "Deletion",
  COMPLAINT: "Complaint",
  OTHER: "Other",
};

export const PRIVACY_SOURCE_LABELS: Record<string, string> = {
  CONTACT_FORM: "Contact page",
  ACCOUNT_CLOSED: "Account closed",
};

/** The short reference shown to the person who made a request (last 8 characters of its id). */
export function requestReference(id: string): string {
  return id.replace(/-/g, "").slice(-8).toUpperCase();
}

/** "10 October 2026" from an ISO date. */
export function policyDate(version: string): string {
  return new Date(`${version}T00:00:00Z`).toLocaleDateString("en-AU", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}
