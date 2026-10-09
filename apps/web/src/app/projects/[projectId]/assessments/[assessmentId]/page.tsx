import type {
  AssessmentOut,
  AssessmentReviewOut,
  AssessmentSummary,
  DocumentOut,
  EvidenceOut,
  GeneratedDocumentOut,
  ReviewSummary,
} from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";

import { AppShell, NoAccess } from "@/components/app/AppShell";
import { AssessmentReport } from "@/components/assessments/AssessmentReport";
import { EvidencePanel } from "@/components/documents/EvidencePanel";
import { ReportDownloads } from "@/components/documents/ReportDownloads";
import { ReviewPanel } from "@/components/review/ReviewPanel";
import { isOpen } from "@/lib/review";
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
  const base = `/organisations/${orgId}`;
  const [found, evidence, documents, generated, reviewState, reviews, assessments] =
    await Promise.all([
      serverGet<AssessmentOut>(`${base}/assessments/${assessmentId}`),
      serverGet<EvidenceOut[]>(`${base}/assessments/${assessmentId}/evidence`),
      serverGet<DocumentOut[]>(`${base}/projects/${projectId}/documents`),
      serverGet<GeneratedDocumentOut[]>(`${base}/projects/${projectId}/generated-documents`),
      serverGet<AssessmentReviewOut>(`${base}/assessments/${assessmentId}/review`),
      serverGet<ReviewSummary[]>(`${base}/projects/${projectId}/reviews`),
      serverGet<AssessmentSummary[]>(`${base}/projects/${projectId}/assessments`),
    ]);
  const assessment = orNotFound(found);
  if (assessment.project_id !== projectId) {
    orNotFound({ ok: false, status: 404 });
  }
  const canWrite = session.permissions.includes("project.write");
  const review = reviewState.ok ? reviewState.data : null;
  const openReview = (reviews.ok ? reviews.data : []).find((r) => isOpen(r.status)) ?? null;
  const latestId = assessments.ok ? assessments.data[0]?.id : undefined;
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
          />
        }
      >
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
        />
      </AssessmentReport>
    </AppShell>
  );
}
