import type {
  AIJobOut,
  AIStatusOut,
  AssessmentOut,
  AssessmentReviewOut,
  AssessmentSummary,
  CatalogueOut,
  DocumentOut,
  EvidenceOut,
  GeneratedDocumentOut,
  ProjectDetailOut,
  ReviewSummary,
} from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";

import { AIExplanation } from "@/components/ai/AIExplanation";
import { GrantDrafts } from "@/components/ai/GrantDrafts";
import { AppShell, NoAccess } from "@/components/app/AppShell";
import { AssessmentReport } from "@/components/assessments/AssessmentReport";
import { EvidencePanel } from "@/components/documents/EvidencePanel";
import { REPORT_TEMPLATES, ReportDownloads } from "@/components/documents/ReportDownloads";
import { ReviewPanel } from "@/components/review/ReviewPanel";
import { MAP_VERTICALS } from "@/lib/assessment";
import { reviewPrice } from "@/lib/billing";
import { firstParam } from "@/lib/redirect";
import { isOpen } from "@/lib/review";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Assessment", robots: { index: false } };

type Props = {
  params: Promise<{ projectId: string; assessmentId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function AssessmentPage({ params, searchParams }: Props) {
  const { projectId, assessmentId } = await params;
  const paymentReturn = firstParam((await searchParams).payment) ?? null;
  const session = await requireSession(`/projects/${projectId}/assessments/${assessmentId}`);
  const orgId = session.active_organisation_id;
  if (!orgId || !session.permissions.includes("project.read")) {
    return (
      <AppShell session={session}>
        <NoAccess what="projects" />
      </AppShell>
    );
  }
  const base = `/organisations/${orgId}`;
  const [
    found,
    evidence,
    documents,
    generated,
    reviewState,
    reviews,
    assessments,
    project,
    aiStatus,
    aiJobs,
    catalogue,
  ] = await Promise.all([
      serverGet<AssessmentOut>(`${base}/assessments/${assessmentId}`),
      serverGet<EvidenceOut[]>(`${base}/assessments/${assessmentId}/evidence`),
      serverGet<DocumentOut[]>(`${base}/projects/${projectId}/documents`),
      serverGet<GeneratedDocumentOut[]>(`${base}/projects/${projectId}/generated-documents`),
      serverGet<AssessmentReviewOut>(`${base}/assessments/${assessmentId}/review`),
      serverGet<ReviewSummary[]>(`${base}/projects/${projectId}/reviews`),
      serverGet<AssessmentSummary[]>(`${base}/projects/${projectId}/assessments`),
      serverGet<ProjectDetailOut>(`${base}/projects/${projectId}`),
      serverGet<AIStatusOut>("/ai/status"),
      serverGet<AIJobOut[]>(`${base}/assessments/${assessmentId}/ai-jobs`),
      serverGet<CatalogueOut>(`${base}/billing/catalogue`),
    ]);
  const assessment = orNotFound(found);
  if (assessment.project_id !== projectId) {
    orNotFound({ ok: false, status: 404 });
  }
  const canWrite = session.permissions.includes("project.write");
  const review = reviewState.ok ? reviewState.data : null;
  const openReview = (reviews.ok ? reviews.data : []).find((r) => isOpen(r.status)) ?? null;
  const latestId = assessments.ok ? assessments.data[0]?.id : undefined;
  const ai = aiStatus.ok && aiStatus.data.enabled ? aiStatus.data : null;
  const jobs = aiJobs.ok ? aiJobs.data : [];
  return (
    <AppShell session={session}>
      <p className="breadcrumb">
        <Link href="/projects">Projects</Link> /{" "}
        <Link href={`/projects/${projectId}`}>Project</Link>
      </p>
      <AssessmentReport
        assessment={assessment}
        projectId={projectId}
        overrides={review?.overrides}
        approvalMap={project.ok && MAP_VERTICALS.has(project.data.vertical)}
        intro={
          <ReviewPanel
            organisationId={orgId}
            projectId={projectId}
            assessmentId={assessment.id}
            isLatest={latestId === assessment.id}
            review={review?.review ?? null}
            openElsewhere={
              openReview && openReview.assessment_id !== assessment.id ? openReview : null
            }
            canWrite={canWrite}
            price={
              catalogue.ok && project.ok
                ? reviewPrice(catalogue.data.products, project.data.vertical)
                : null
            }
            paymentReturn={paymentReturn}
          />
        }
      >
        {ai && assessment.finding_list.length > 0 ? (
          <AIExplanation
            organisationId={orgId}
            assessmentId={assessment.id}
            jobs={jobs}
            findingTitles={Object.fromEntries(
              assessment.finding_list.map((f) => [f.id, f.title ?? f.rule_title]),
            )}
            canWrite={canWrite}
            mock={ai.mock}
          />
        ) : null}
        {ai && assessment.grant_matches && assessment.grant_matches.length > 0 ? (
          <GrantDrafts
            organisationId={orgId}
            assessmentId={assessment.id}
            matches={assessment.grant_matches}
            jobs={jobs}
            labels={assessment.fact_labels}
            canWrite={canWrite}
            mock={ai.mock}
          />
        ) : null}
        <EvidencePanel
          organisationId={orgId}
          projectId={projectId}
          requirements={assessment.evidence_requirements}
          evidence={evidence.ok ? evidence.data : []}
          documents={documents.ok ? documents.data : []}
          canWrite={canWrite}
        />
        <ReportDownloads
          organisationId={orgId}
          assessmentId={assessment.id}
          generated={(generated.ok ? generated.data : []).filter(
            (g) => g.assessment_id === assessment.id,
          )}
          canWrite={canWrite}
          templates={project.ok ? REPORT_TEMPLATES[project.data.vertical] : undefined}
        />
      </AssessmentReport>
    </AppShell>
  );
}
