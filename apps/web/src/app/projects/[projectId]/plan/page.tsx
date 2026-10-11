import type {
  AssessmentSummary,
  DocumentOut,
  ProjectDetailOut,
  ProjectPlanOut,
} from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";

import { AppShell, NoAccess } from "@/components/app/AppShell";
import { PlanOffer } from "@/components/plans/PlanOffer";
import { ProjectPlan } from "@/components/plans/ProjectPlan";
import { firstParam } from "@/lib/redirect";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Project plan", robots: { index: false } };

type Props = {
  params: Promise<{ projectId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

/** The project plan: what it is and starting it, or the plan itself. */
export default async function ProjectPlanPage({ params, searchParams }: Props) {
  const { projectId } = await params;
  const paymentReturn = firstParam((await searchParams).payment) ?? null;
  const session = await requireSession(`/projects/${projectId}/plan`);
  const orgId = session.active_organisation_id;
  if (!orgId || !session.permissions.includes("project.read")) {
    return (
      <AppShell session={session}>
        <NoAccess what="projects" />
      </AppShell>
    );
  }
  const base = `/organisations/${orgId}/projects/${projectId}`;
  const [project, plan, documents, assessments] = await Promise.all([
    serverGet<ProjectDetailOut>(base),
    serverGet<ProjectPlanOut>(`${base}/plan`),
    serverGet<DocumentOut[]>(`${base}/documents`),
    serverGet<AssessmentSummary[]>(`${base}/assessments`),
  ]);
  const found = orNotFound(project);
  const current = orNotFound(plan);
  const latest = assessments.ok ? (assessments.data[0]?.id ?? null) : null;
  const canWrite = session.permissions.includes("project.write");
  return (
    <AppShell session={session}>
      <p className="breadcrumb">
        <Link href="/projects">Projects</Link> /{" "}
        <Link href={`/projects/${projectId}`}>{found.title}</Link>
      </p>
      {current.status === "ACTIVE" ? (
        <ProjectPlan
          organisationId={orgId}
          projectId={projectId}
          assessmentId={latest}
          plan={current}
          documents={documents.ok ? documents.data : []}
          canWrite={canWrite}
        />
      ) : (
        <>
          <h1 className="page-title">Project plan</h1>
          <PlanOffer
            organisationId={orgId}
            projectId={projectId}
            plan={current}
            hasAssessment={latest !== null}
            canWrite={canWrite}
            paymentReturn={paymentReturn}
          />
        </>
      )}
    </AppShell>
  );
}
