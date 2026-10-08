import type { AssessmentOut } from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";

import { AppShell, NoAccess } from "@/components/app/AppShell";
import { AssessmentReport } from "@/components/assessments/AssessmentReport";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Assessment", robots: { index: false } };

type Props = { params: Promise<{ projectId: string; assessmentId: string }> };

export default async function AssessmentPage({ params }: Props) {
  const { projectId, assessmentId } = await params;
  const session = await requireSession(`/projects/${projectId}/assessments/${assessmentId}`);
  const orgId = session.active_organisation_id;
  if (!orgId || !session.permissions.includes("project.read")) {
    return (
      <AppShell session={session}>
        <NoAccess what="projects" />
      </AppShell>
    );
  }
  const assessment = orNotFound(
    await serverGet<AssessmentOut>(`/organisations/${orgId}/assessments/${assessmentId}`),
  );
  if (assessment.project_id !== projectId) {
    orNotFound({ ok: false, status: 404 });
  }
  return (
    <AppShell session={session}>
      <p className="breadcrumb">
        <Link href="/projects">Projects</Link> /{" "}
        <Link href={`/projects/${projectId}`}>Project</Link>
      </p>
      <AssessmentReport assessment={assessment} projectId={projectId} />
    </AppShell>
  );
}
