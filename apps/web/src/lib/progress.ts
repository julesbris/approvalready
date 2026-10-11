/** Keep going (stuck projects): what each stage means to staff. */

import type { QuietProjectOut } from "@approvalready/shared-types";

export const STAGE_LABELS: Record<string, string> = {
  START: "Hasn't started the questions",
  QUESTIONS: "Answering the questions",
  RESULTS: "Hasn't run the assessment",
  DOCUMENTS: "Sending documents",
  TASKS: "Working through tasks",
};

export const QUIET_FILTERS = [1, 3, 7, 30] as const;

/** The quiet filter from the address, falling back to a day. */
export function quietDays(value: string | undefined): number {
  const days = Number(value);
  return (QUIET_FILTERS as readonly number[]).includes(days) ? days : 1;
}

/** "3 tasks, 2 documents" for what is still open on a quiet project. */
export function openSummary(p: QuietProjectOut): string {
  const parts: string[] = [];
  const add = (n: number, one: string, many: string) => {
    if (n > 0) parts.push(`${n} ${n === 1 ? one : many}`);
  };
  add(p.documents_missing, "document", "documents");
  add(p.open_tasks, "task", "tasks");
  add(p.checklist_open, "checklist item", "checklist items");
  return parts.join(", ") || "None";
}

/** Whole days between ``iso`` and ``now``. */
export function daysSince(iso: string, now: Date = new Date()): number {
  return Math.max(0, Math.floor((now.getTime() - new Date(iso).getTime()) / 86_400_000));
}
