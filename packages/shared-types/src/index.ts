/**
 * API contracts shared by the web app. `api.ts` is generated from the FastAPI OpenAPI
 * schema (`npm run generate:types` at the repo root); never edit it by hand. CI fails if
 * it is out of date with the API.
 */

import type { components, paths } from "./api";

export type { components, paths };

type Schemas = components["schemas"];

export type LiveResponse = Schemas["LiveResponse"];
export type DependencyCheck = Schemas["DependencyCheck"];
export type ReadyResponse = Schemas["ReadyResponse"];
export type VersionResponse = Schemas["VersionResponse"];
export type CheckStatus = DependencyCheck["status"];

export type SessionOut = Schemas["SessionOut"];
export type UserOut = Schemas["UserOut"];
export type MembershipOut = Schemas["MembershipOut"];
export type OrganisationOut = Schemas["OrganisationOut"];
export type MemberOut = Schemas["MemberOut"];
export type InvitationOut = Schemas["InvitationOut"];
export type AuditEventOut = Schemas["AuditEventOut"];

export type ProjectOut = Schemas["ProjectOut"];
export type ProjectDetailOut = Schemas["ProjectDetailOut"];
export type ProjectCreate = Schemas["ProjectCreate"];
export type ProjectStatus = Schemas["ProjectStatus"];
export type StatusEventOut = Schemas["StatusEventOut"];
export type TaskOut = Schemas["TaskOut"];
export type ReminderOut = Schemas["ReminderOut"];
export type SubmissionSummary = Schemas["SubmissionSummary"];
export type SubmissionOut = Schemas["SubmissionOut"];
export type QuestionnaireOut = Schemas["QuestionnaireOut"];
export type QuestionnaireSummary = Schemas["QuestionnaireSummary"];
export type SectionOut = Schemas["SectionOut"];
export type QuestionOut = Schemas["QuestionOut"];
export type OptionOut = Schemas["OptionOut"];
export type PropertyOut = Schemas["PropertyOut"];
export type VesselOut = Schemas["VesselOut"];
export type BusinessProfileOut = Schemas["BusinessOut"];

/** Error body returned by the API for every handled error. */
export interface ApiErrorBody {
  detail:
    | { code: string; message: string; fields?: Record<string, string> }
    | Array<{ msg: string; loc: (string | number)[] }>;
}

/** Regulatory confidence levels. Every regulatory outcome uses exactly one of these. */
export const CONFIDENCE_LEVELS = ["VERIFIED", "LIKELY", "REVIEW_REQUIRED", "UNKNOWN"] as const;
export type Confidence = (typeof CONFIDENCE_LEVELS)[number];

export const VERTICALS = ["PLANNING", "VESSEL", "BUSINESS", "GRANT", "SELL", "RENT"] as const;
export type Vertical = (typeof VERTICALS)[number];
