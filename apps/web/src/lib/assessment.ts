/**
 * Presenting assessments: plain-language labels for confidence and outcomes, and turning a
 * finding's stored trace into "because" sentences built from the customer's own answers.
 */

import type {
  Certainty,
  Confidence,
  FindingOut,
  FindingSourceOut,
} from "@approvalready/shared-types";

export const CONFIDENCE_LABELS: Record<Confidence, string> = {
  VERIFIED: "Verified",
  LIKELY: "Likely",
  REVIEW_REQUIRED: "Needs professional review",
  UNKNOWN: "Not enough information",
};

export const CONFIDENCE_HELP: Record<Confidence, string> = {
  VERIFIED: "Based on sources our team has checked and that are in force today.",
  LIKELY: "Based on sources that have not all been checked by our team yet.",
  REVIEW_REQUIRED:
    "A source behind this is disputed, out of date or has changed. Have a professional confirm it.",
  UNKNOWN: "We need more information from you before we can say.",
};

export const OUTCOME_LABELS: Record<string, string> = {
  APPROVAL_REQUIRED: "Approval required",
  APPROVAL_LIKELY: "Approval likely required",
  NOT_REQUIRED: "Not required",
  EVIDENCE_REQUIRED: "Evidence needed",
  PROFESSIONAL_REQUIRED: "Professional needed",
  REFERRAL_CATEGORY: "Specialist help",
  CROSS_SELL: "Related",
  WARNING: "Warning",
  INFO: "Information",
};

export const RESULT_LABELS: Record<string, string> = {
  MATCH: "Applies",
  NO_MATCH: "Does not apply",
  UNKNOWN: "Unknown",
};

export const VERIFICATION_LABELS: Record<string, string> = {
  UNVERIFIED: "Not yet verified",
  VERIFIED: "Verified",
  DISPUTED: "Disputed",
  SUPERSEDED: "Superseded",
};

export const OUTCOME_TYPES = Object.keys(OUTCOME_LABELS);

export const CERTAINTY_LABELS: Record<Certainty, string> = {
  REQUIRED: "Required",
  LIKELY_REQUIRED: "Likely required",
  MAY_APPLY: "May apply",
  NOT_IDENTIFIED: "Not identified",
};

/** Every source cited by any finding, once, in the order first cited. */
export function uniqueSources(findings: FindingOut[]): FindingSourceOut[] {
  const seen = new Map<string, FindingSourceOut>();
  for (const f of findings) {
    for (const s of f.sources) {
      if (!seen.has(s.reference_id)) seen.set(s.reference_id, s);
    }
  }
  return [...seen.values()];
}

const OPERATOR_TEXT: Record<string, string> = {
  equals: "is",
  not_equals: "is not",
  greater_than: "is more than",
  less_than: "is less than",
  greater_equal: "is at least",
  less_equal: "is at most",
  contains: "includes",
  not_contains: "does not include",
  in: "is one of",
  not_in: "is not one of",
  exists: "is provided",
  missing: "is not provided",
};

export type TraceNode = {
  kind: "all" | "any" | "not" | "leaf";
  result: "TRUE" | "FALSE" | "UNKNOWN";
  children?: TraceNode[];
  fact?: string;
  op?: string;
  value?: unknown;
  actual?: unknown;
  missing?: boolean;
};

export function leaves(node: TraceNode): TraceNode[] {
  if (node.kind === "leaf") return [node];
  return (node.children ?? []).flatMap(leaves);
}

export function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "not answered";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (Array.isArray(value)) return value.map(formatValue).join(", ");
  if (typeof value === "object") {
    const decimal = (value as { $decimal?: unknown }).$decimal;
    if (typeof decimal === "string") return decimal;
    return Object.values(value as Record<string, unknown>)
      .map(formatValue)
      .join(", ");
  }
  return String(value).replaceAll("_", " ");
}

export function factLabel(fact: string, labels: Record<string, string>): string {
  return labels[fact] ?? fact;
}

/** One condition check as a sentence, e.g. "Floor area: you said 92.5 (rule: is more than 80)". */
export function describeLeaf(leaf: TraceNode, labels: Record<string, string>): string {
  const label = factLabel(leaf.fact ?? "", labels);
  const rule = `${OPERATOR_TEXT[leaf.op ?? ""] ?? leaf.op}${
    leaf.value === undefined || leaf.value === null ? "" : ` ${formatValue(leaf.value)}`
  }`;
  if (leaf.missing && leaf.op !== "exists" && leaf.op !== "missing") {
    return `${label}: not answered (needed to check whether it ${rule})`;
  }
  return `${label}: ${formatValue(leaf.actual)} (checked: ${rule})`;
}

/** Findings people need to act on first, then missing information, then the rest. */
export function groupFindings<T extends FindingOut>(
  findings: T[],
): {
  action: T[];
  missing: T[];
  other: T[];
} {
  const actionTypes = new Set([
    "APPROVAL_REQUIRED",
    "APPROVAL_LIKELY",
    "EVIDENCE_REQUIRED",
    "PROFESSIONAL_REQUIRED",
    "WARNING",
  ]);
  return {
    action: findings.filter((f) => f.result !== "UNKNOWN" && actionTypes.has(f.outcome_type ?? "")),
    missing: findings.filter((f) => f.result === "UNKNOWN"),
    other: findings.filter(
      (f) => f.result !== "UNKNOWN" && !actionTypes.has(f.outcome_type ?? "") && f.outcome_type,
    ),
  };
}
