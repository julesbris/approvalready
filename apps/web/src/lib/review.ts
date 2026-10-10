/**
 * Professional review: plain-language labels, and findings as the customer should read them
 * once a reviewer has changed some (the original stays visible next to the change).
 */

import type {
  CredentialKind,
  Decision,
  Discipline,
  FindingOut,
  OverrideOut,
  ProfessionalStatus,
  RefundOut,
  RefundReason,
  ReviewOut,
  ReviewRequestStatus,
  ReviewStatus,
} from "@approvalready/shared-types";

import { formatMoney } from "./billing";

export const REVIEW_STATUS_LABELS: Record<ReviewRequestStatus, string> = {
  PAYMENT_PENDING: "Waiting for payment",
  REVIEW_REQUESTED: "Waiting for a reviewer",
  ASSIGNED: "Reviewer assigned",
  IN_REVIEW: "Being reviewed",
  CHANGES_REQUIRED: "Changes requested",
  APPROVED: "Approved",
  COMPLETED: "Reviewed, not approved",
  CANCELLED: "Cancelled",
};

/** Where an assessment stands with review, as reports describe it. */
export const REPORT_REVIEW_LABELS: Record<ReviewStatus, string> = {
  NOT_REVIEWED: "Not reviewed by a professional",
  IN_REVIEW: "Professional review in progress",
  CHANGES_REQUIRED: "Changes requested by the reviewer",
  APPROVED: "Reviewed and approved by a professional",
  REVIEWED: "Reviewed by a professional, not approved",
};

export const DECISION_LABELS: Record<Decision, string> = {
  CHANGES_REQUIRED: "Ask for changes",
  APPROVED: "Approve",
  COMPLETED: "Finish without approving",
};

export const DECISION_DONE: Record<Decision, string> = {
  CHANGES_REQUIRED: "Asked for changes",
  APPROVED: "Approved",
  COMPLETED: "Finished without approving",
};

export const DISCIPLINE_LABELS: Record<Discipline, string> = {
  TOWN_PLANNER: "Town planner",
  SURVEYOR: "Surveyor",
  BUILDING_CERTIFIER: "Building certifier",
  BUILDING_DESIGNER: "Building designer",
  ENGINEER: "Engineer",
  MARINE_SURVEYOR: "Marine surveyor",
  LAWYER: "Lawyer",
  ACCOUNTANT: "Accountant",
  GRANT_WRITER: "Grant writer",
  OTHER: "Other professional",
};

export const CREDENTIAL_KIND_LABELS: Record<CredentialKind, string> = {
  LICENCE: "Licence",
  REGISTRATION: "Registration",
  MEMBERSHIP: "Professional membership",
  INSURANCE: "Professional indemnity insurance",
  QUALIFICATION: "Qualification",
};

export const PROFESSIONAL_STATUS_LABELS: Record<ProfessionalStatus, string> = {
  PENDING: "Waiting for checks",
  ACTIVE: "Active",
  SUSPENDED: "Suspended",
};

/** Statuses in which the customer can still cancel, comment or wait on the reviewer. */
export const OPEN_REVIEW_STATUSES: ReviewRequestStatus[] = [
  "PAYMENT_PENDING",
  "REVIEW_REQUESTED",
  "ASSIGNED",
  "IN_REVIEW",
  "CHANGES_REQUIRED",
];

export function isOpen(status: ReviewRequestStatus): boolean {
  return OPEN_REVIEW_STATUSES.includes(status);
}

export type ReviewedFinding = FindingOut & {
  /** The reviewer's current change, when there is one. */
  override: OverrideOut | null;
  /** What the assessment itself said. */
  original: { outcome_type: FindingOut["outcome_type"]; confidence: FindingOut["confidence"] };
};

/** Findings with each one's latest reviewer change applied. */
export function applyOverrides(
  findings: FindingOut[],
  overrides: OverrideOut[] = [],
): ReviewedFinding[] {
  const current = new Map(overrides.filter((o) => o.current).map((o) => [o.finding_id, o]));
  return findings.map((f) => {
    const o = current.get(f.id) ?? null;
    return {
      ...f,
      outcome_type: o ? o.new_outcome_type : f.outcome_type,
      confidence: o ? o.new_confidence : f.confidence,
      override: o,
      original: { outcome_type: f.outcome_type, confidence: f.confidence },
    };
  });
}

/** The reviewer as customers see them: "Pat Planner, Town planner (Coastal Planning)". */
export function reviewerName(p: {
  display_name: string;
  discipline: Discipline;
  practice_name: string;
}): string {
  return `${p.display_name}, ${DISCIPLINE_LABELS[p.discipline]} (${p.practice_name})`;
}

export function reviewDocumentUrl(reviewId: string, documentId: string): string {
  return `/api/v1/professional/reviews/${reviewId}/documents/${documentId}/content`;
}

/** What the customer is asked before cancelling, saying whether they get their money back. */
export function cancelQuestion(review: ReviewOut): string {
  const payment = review.payment;
  if (payment && review.cancel_refund_cents > 0) {
    const amount = formatMoney(review.cancel_refund_cents, payment.currency);
    return (
      `Cancel this review? No reviewer has started, so we'll refund ${amount} to the card ` +
      "or account you paid with."
    );
  }
  if (payment?.paid_at && review.status !== "PAYMENT_PENDING") {
    return (
      "Cancel this review? Your reviewer has already started, so it isn't refunded " +
      "automatically. Contact us if you think a refund is fair."
    );
  }
  return "Cancel this review?";
}

/** A refund on the review's payment, as the customer should read it. */
export function refundLine(r: RefundOut): string {
  const amount = formatMoney(r.amount_cents, r.currency);
  if (r.status === "FAILED") {
    return `Your refund of ${amount} is delayed. We're sorting it out and will email you.`;
  }
  if (r.status === "PENDING") return `Refund of ${amount}: being sent.`;
  return `Refunded ${amount}. Most banks show it within 5 to 10 business days.`;
}

export const REFUND_REASON_LABELS: Record<RefundReason, string> = {
  REVIEW_CANCELLED: "Cancelled before work started",
  PAID_AFTER_CANCEL: "Paid after the review was cancelled",
  STAFF: "Refunded by staff",
};
