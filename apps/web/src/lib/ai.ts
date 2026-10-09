import type { AIJobOut } from "@approvalready/shared-types";

import { apiRequest } from "@/lib/client-api";
import { waitUntil } from "@/lib/documents";

export type AITask = AIJobOut["task"];

/** The draft to show for a task (and program): the newest one that worked, else the newest. */
export function currentJob(
  jobs: AIJobOut[],
  task: AITask,
  subjectId: string | null = null,
): AIJobOut | undefined {
  const mine = jobs
    .filter((j) => j.task === task && (subjectId === null || j.subject_id === subjectId))
    .sort((a, b) => b.created_at.localeCompare(a.created_at));
  const newest = mine[0];
  if (newest && newest.status === "PENDING") return newest;
  return mine.find((j) => j.status === "SUCCEEDED") ?? newest;
}

export function waitForJob(organisationId: string, job: AIJobOut, intervalMs?: number) {
  return waitUntil(
    () => apiRequest<AIJobOut>("GET", `/organisations/${organisationId}/ai-jobs/${job.id}`),
    (j) => j.status !== "PENDING",
    { intervalMs },
  );
}

export const AI_DRAFT_NOTICE =
  "Written by AI from the findings above. It only rewords them: it cannot add requirements, " +
  "and we check that it names only these findings and no figures, dates or links they don't " +
  "contain. The findings and their sources are what count.";
