/**
 * API contracts shared by the web app and (later) generated from the FastAPI OpenAPI schema.
 * Keep in sync with apps/api/app/api/health.py until codegen is introduced (Milestone 2).
 */

export type CheckStatus = "ok" | "error";

export interface LiveResponse {
  status: "ok";
}

export interface DependencyCheck {
  status: CheckStatus;
  latency_ms: number;
}

export interface ReadyResponse {
  status: CheckStatus;
  checks: Record<string, DependencyCheck>;
}

export interface VersionResponse {
  name: string;
  version: string;
  git_sha: string;
  environment: string;
}

/** Regulatory confidence levels. Every regulatory outcome uses exactly one of these. */
export const CONFIDENCE_LEVELS = ["VERIFIED", "LIKELY", "REVIEW_REQUIRED", "UNKNOWN"] as const;
export type Confidence = (typeof CONFIDENCE_LEVELS)[number];

export const VERTICALS = ["PLANNING", "VESSEL", "BUSINESS", "GRANT", "SELL", "RENT"] as const;
export type Vertical = (typeof VERTICALS)[number];
