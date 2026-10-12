import type {
  ApprovalGuideOut,
  OfficialForm,
  AssessmentOut,
  PrefillOut,
  ProjectDetailOut,
  SubmissionOut,
} from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";

import { AppShell, NoAccess } from "@/components/app/AppShell";
import { StartQuestionnaire } from "@/components/questionnaire/StartQuestionnaire";
import { QuestionnaireRunner } from "@/components/questionnaire/QuestionnaireRunner";
import { guideKinds, guideQuery } from "@/lib/approvalGuides";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Your answers", robots: { index: false } };

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
  const prefill =
    submission && canWrite && submission.status === "IN_PROGRESS"
      ? await serverGet<PrefillOut>(`${base}/submissions/${submission.id}/prefill`)
      : null;
  // The result of these answers, shown under them: the latest assessment made from them.
  const assessed =
    submission && project.latest_assessment?.submission_id === submission.id
      ? await serverGet<AssessmentOut>(`${base}/assessments/${project.latest_assessment.id}`)
      : null;
  const assessment = assessed?.ok ? assessed.data : null;
  const kinds = assessment ? guideKinds(assessment) : [];
  const guides =
    kinds.length > 0
      ? await serverGet<ApprovalGuideOut[]>(
          `/guidance/approvals?${guideQuery(kinds, project.vertical)}`,
        )
      : null;
  // The product's official forms, so every form the result names links to it.
  const forms = await serverGet<OfficialForm[]>(`/guidance/forms?vertical=${project.vertical}`);
  return (
    <AppShell session={session}>
      <div className="flow">
        <p className="breadcrumb">
          <Link href="/projects">Projects</Link> /{" "}
          <Link href={`/projects/${projectId}`}>{project.title}</Link>
        </p>
        {submission ? (
          <QuestionnaireRunner
            organisationId={orgId}
            projectId={projectId}
            submission={submission}
            canWrite={canWrite}
            suggestions={prefill?.ok ? prefill.data.suggestions : []}
            assessment={assessment}
            guides={guides?.ok ? guides.data : []}
            forms={forms.ok ? forms.data : []}
          />
        ) : canWrite ? (
          <StartQuestionnaire organisationId={orgId} projectId={projectId} />
        ) : (
          <p>No answers yet.</p>
        )}
      </div>
    </AppShell>
  );
}
