/** Plain-language labels for API enums. */

import type { ProjectStatus, Vertical } from "@approvalready/shared-types";

import { defaultBrand } from "@/lib/brand";

export function verticalName(vertical: string): string {
  return defaultBrand.products.find((p) => p.key === vertical)?.name ?? vertical;
}

export const STATUS_LABELS: Record<ProjectStatus, string> = {
  DRAFT: "Draft",
  IN_PROGRESS: "In progress",
  ASSESSED: "Assessed",
  IN_REVIEW: "In professional review",
  COMPLETED: "Completed",
  ARCHIVED: "Archived",
};

/** Button text for moving a project to a status. */
export const STATUS_ACTIONS: Record<ProjectStatus, string> = {
  DRAFT: "Move to draft",
  IN_PROGRESS: "Mark as in progress",
  ASSESSED: "Mark as assessed",
  IN_REVIEW: "Send for review",
  COMPLETED: "Mark as completed",
  ARCHIVED: "Archive",
};

export function statusLabel(status: string): string {
  return STATUS_LABELS[status as ProjectStatus] ?? status;
}

export const SUBMISSION_LABELS: Record<string, string> = {
  IN_PROGRESS: "In progress",
  SUBMITTED: "Submitted",
};

export const ROLE_LABELS: Record<string, string> = {
  CUSTOMER: "Projects",
  ORG_ADMIN: "Administrator",
  PROFESSIONAL: "Professional reviewer",
  PARTNER_USER: "Partner user",
  PARTNER_ADMIN: "Partner administrator",
  STAFF: "Staff",
  ADMIN: "Platform administrator",
  SUPERADMIN: "Super administrator",
};

export const ROLE_HELP: Record<string, string> = {
  CUSTOMER: "Can see, create and edit projects.",
  ORG_ADMIN: "Can manage the organisation's details and members.",
  PROFESSIONAL: "Can perform professional reviews.",
  PARTNER_USER: "Can see the partner account and, once referrals open, its leads.",
  PARTNER_ADMIN: "Can manage the partner profile, plan, billing and members.",
};

/** Roles a member can be given, by organisation kind (mirrors the API's role catalogue). */
export const ASSIGNABLE_ROLES: Record<string, string[]> = {
  PERSONAL: ["CUSTOMER", "ORG_ADMIN"],
  BUSINESS: ["CUSTOMER", "ORG_ADMIN"],
  PROFESSIONAL_PRACTICE: ["ORG_ADMIN", "PROFESSIONAL"],
  PARTNER: ["PARTNER_USER", "PARTNER_ADMIN"],
};

export const KIND_LABELS: Record<string, string> = {
  PERSONAL: "Personal account",
  BUSINESS: "Business",
  PROFESSIONAL_PRACTICE: "Professional practice",
  PARTNER: "Partner",
  PLATFORM_ADMIN: "ApprovalReady administration",
};

export function roleList(roles: readonly string[]): string {
  return roles.map((r) => ROLE_LABELS[r] ?? r).join(", ");
}

export function isVertical(value: unknown): value is Vertical {
  return typeof value === "string" && defaultBrand.products.some((p) => p.key === value);
}

export function formatDateTime(iso: string): string {
  return new Intl.DateTimeFormat("en-AU", { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(iso),
  );
}
