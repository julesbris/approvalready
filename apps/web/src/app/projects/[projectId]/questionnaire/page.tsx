import type { ProjectDetailOut, SubmissionOut } from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";

import { AppShell, NoAccess } from "@/components/app/AppShell";
import { StartQuestionnaire } from "@/components/questionnaire/StartQuestionnaire";
import { QuestionnaireRunner } from "@/components/questionnaire/QuestionnaireRunner";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Questionnaire", robots: { index: false } };

type Props = { params: Promise<{ projectId: string }> };

export default async function QuestionnairePage({ params }: Props) {
  const { projectId } = await params;
  const session = await requireSession(`/projects/${projectId}/questionnaire`);
  const orgId = session.active_organisation_id;
  if (!orgId || !session.permissions.includes("project.read")) {
    return (
      <AppShell session={session}>
        <NoAccess what="projects" />
      </AppShell>
    );
  }
  const canWrite = session.permissions.includes("project.write");
  const base = `/organisations/${orgId}`;
  const project = orNotFound(await serverGet<ProjectDetailOut>(`${base}/projects/${projectId}`));
  // One questionnaire per vertical today: open the most recently updated answers.
  const latest = [...project.submissions].sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0];
  const submission = latest
    ? orNotFound(await serverGet<SubmissionOut>(`${base}/submissions/${latest.id}`))
    : null;
  return (
    <AppShell session={session}>
      <p className="breadcrumb">
        <Link href="/projects">Projects</Link> / <Link href={`/projects/${projectId}`}>{project.title}</Link>
      </p>
      {submission ? (
        <QuestionnaireRunner
          organisationId={orgId}
          projectId={projectId}
          submission={submission}
          canWrite={canWrite}
        />
      ) : canWrite ? (
        <StartQuestionnaire organisationId={orgId} projectId={projectId} />
      ) : (
        <p>No answers yet.</p>
      )}
    </AppShell>
  );
}
