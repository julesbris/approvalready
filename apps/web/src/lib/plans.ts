/** Project plans: progress, section states and keeping the plan up to date in the browser. */

import type { PlanSectionOut, PlanStepOut, ProjectPlanOut } from "@approvalready/shared-types";

export type SectionState = "DONE" | "OVERDUE" | "UNDER_WAY" | "NOT_STARTED";

export const SECTION_STATE_LABELS: Record<SectionState, string> = {
  DONE: "Done",
  OVERDUE: "Overdue",
  UNDER_WAY: "Under way",
  NOT_STARTED: "Not started",
};

/** The `status-…` chip class for each state (teal only for done). */
export const SECTION_STATE_CLASSES: Record<SectionState, string> = {
  DONE: "status-completed",
  OVERDUE: "status-failed",
  UNDER_WAY: "status-in_progress",
  NOT_STARTED: "status-draft",
};

export const KIND_LABELS: Record<string, string> = {
  PREPARE: "Have ready",
  STEP: "Step",
  DOCUMENT: "Document",
  TASK: "Task",
  CHECK: "Checklist",
  FOLLOW_UP: "Follow-up call",
  CUSTOM: "Your step",
};

/** Today in Brisbane as YYYY-MM-DD (due dates are calendar days there). */
export function todayIso(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Australia/Brisbane" }).format(now);
}

function counted(steps: PlanStepOut[]): PlanStepOut[] {
  return steps.filter((s) => s.status !== "NOT_APPLICABLE");
}

export function isOverdue(step: PlanStepOut, today: string): boolean {
  return step.status === "OPEN" && step.due_on !== null && step.due_on < today;
}

export function sectionState(section: PlanSectionOut, today: string): SectionState {
  const steps = counted(section.steps);
  if (steps.length > 0 && steps.every((s) => s.status === "DONE")) return "DONE";
  if (steps.some((s) => isOverdue(s, today))) return "OVERDUE";
  if (steps.some((s) => s.status === "DONE")) return "UNDER_WAY";
  return "NOT_STARTED";
}

/** The section's counts and dates worked out again from its steps. */
function recount(section: PlanSectionOut): PlanSectionOut {
  const steps = counted(section.steps);
  const dates = section.steps.flatMap((s) => (s.due_on ? [s.due_on] : [])).sort();
  return {
    ...section,
    done: steps.filter((s) => s.status === "DONE").length,
    total: steps.length,
    starts_on: dates[0] ?? null,
    ends_on: dates[dates.length - 1] ?? null,
  };
}

/** The plan's progress worked out again from every step (as the API does). */
export function withProgress(plan: ProjectPlanOut, today: string = todayIso()): ProjectPlanOut {
  const all = plan.sections.flatMap((s) => s.steps);
  const steps = counted(all);
  const done = steps.filter((s) => s.status === "DONE").length;
  const open = steps.filter((s) => s.status === "OPEN");
  const dated = open
    .filter((s) => s.due_on !== null)
    .sort((a, b) => (a.due_on ?? "").localeCompare(b.due_on ?? ""));
  const week = new Date(`${today}T00:00:00Z`);
  week.setUTCDate(week.getUTCDate() + 7);
  const weekIso = week.toISOString().slice(0, 10);
  const dates = steps.flatMap((s) => (s.due_on ? [s.due_on] : [])).sort();
  return {
    ...plan,
    progress: {
      total: steps.length,
      done,
      percent: steps.length ? Math.round((100 * done) / steps.length) : 0,
      overdue: dated.filter((s) => (s.due_on ?? "") < today).length,
      due_this_week: dated.filter((s) => (s.due_on ?? "") >= today && (s.due_on ?? "") <= weekIso)
        .length,
      next_item_id: dated[0]?.id ?? open[0]?.id ?? null,
      finish_on: dates[dates.length - 1] ?? null,
    },
  };
}

/** Put a changed (or new) step into its section, keeping the order. */
export function putStep(plan: ProjectPlanOut, step: PlanStepOut): ProjectPlanOut {
  let sections = plan.sections.map((s) =>
    s.key === step.section_key
      ? recount({
          ...s,
          steps: s.steps.some((x) => x.id === step.id)
            ? s.steps.map((x) => (x.id === step.id ? step : x))
            : [...s.steps, step],
        })
      : s,
  );
  if (!sections.some((s) => s.key === step.section_key)) {
    sections = [
      ...sections,
      recount({
        key: step.section_key,
        kind: "OWN",
        title: "Your own steps and follow-ups",
        fees: [],
        contacts: [],
        watch_out: [],
        sources: [],
        gaps: [],
        help: [],
        verified: false,
        steps: [step],
        done: 0,
        total: 0,
        starts_on: null,
        ends_on: null,
      }),
    ];
  }
  return withProgress({ ...plan, sections });
}

export function dropStep(plan: ProjectPlanOut, stepId: string): ProjectPlanOut {
  return withProgress({
    ...plan,
    sections: plan.sections.map((s) =>
      s.steps.some((x) => x.id === stepId)
        ? recount({ ...s, steps: s.steps.filter((x) => x.id !== stepId) })
        : s,
    ),
  });
}

/** "In 3 days", "Today", "2 days overdue". */
export function dueLabel(dueOn: string, today: string): string {
  const days = Math.round(
    (Date.parse(`${dueOn}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / 86_400_000,
  );
  if (days === 0) return "Due today";
  if (days === 1) return "Due tomorrow";
  if (days > 1) return `Due in ${days} days`;
  return days === -1 ? "1 day overdue" : `${-days} days overdue`;
}

/** Where to ask for introductions for one kind of help (the form ticks it for you). */
export function introductionHref(projectId: string, assessmentId: string, category: string) {
  const params = new URLSearchParams({ assessment: assessmentId, category });
  return `/projects/${projectId}/referrals?${params.toString()}`;
}

/** A website as a link target ("example.com.au" becomes "https://example.com.au"). */
export function websiteHref(website: string): string {
  return /^https?:\/\//i.test(website) ? website : `https://${website}`;
}
