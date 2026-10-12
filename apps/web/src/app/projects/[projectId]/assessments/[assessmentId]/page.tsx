import type {
  AIJobOut,
  ApprovalGuideOut,
  OfficialForm,
  AIStatusOut,
  AssessmentOut,
  AssessmentReviewOut,
  AssessmentSummary,
  CatalogueOut,
  CouncilOut,
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
import { CouncilGuide } from "@/components/councils/CouncilGuide";
import { EvidencePanel } from "@/components/documents/EvidencePanel";
import { REPORT_TEMPLATES, ReportDownloads } from "@/components/documents/ReportDownloads";
import { ReviewPanel } from "@/components/review/ReviewPanel";
import { MAP_VERTICALS } from "@/lib/assessment";
import { guideKinds, guideQuery } from "@/lib/approvalGuides";
import { reviewPrice } from "@/lib/billing";
import { councilKey } from "@/lib/councils";
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
  // Step-by-step guides for the approvals found, in the order to do them.
  const kinds = guideKinds(assessment);
  const vertical = project.ok ? project.data.vertical : undefined;
  const guides =
    kinds.length > 0
      ? await serverGet<ApprovalGuideOut[]>(`/guidance/approvals?${guideQuery(kinds, vertical)}`)
      : null;
  // The product's official forms, so every form the findings name links to it.
  const forms = vertical
    ? await serverGet<OfficialForm[]>(`/guidance/forms?vertical=${vertical}`)
    : null;
  const canWrite = session.permissions.includes("project.write");
  const review = reviewState.ok ? reviewState.data : null;
  const openReview = (reviews.ok ? reviews.data : []).find((r) => isOpen(r.status)) ?? null;
  const latestId = assessments.ok ? assessments.data[0]?.id : undefined;
  const ai = aiStatus.ok && aiStatus.data.enabled ? aiStatus.data : null;
  const jobs = aiJobs.ok ? aiJobs.data : [];
  // Planning: how to apply to the council the assessed answers name.
  const key = councilKey(assessment.facts["property.lga"]);
  const council = key ? await serverGet<CouncilOut>(`/councils/${key}`) : null;
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
        guides={guides?.ok ? guides.data : []}
        forms={forms?.ok ? forms.data : []}
        helpAction={
          <div className="button-row">
            {canWrite && latestId === assessment.id ? (
              <Link
                className="button"
                href={`/projects/${projectId}/referrals?assessment=${assessment.id}`}
              >
                Introduce me to checked partners
              </Link>
            ) : null}
            <Link className="button-secondary" href={`/projects/${projectId}/referrals`}>
              Your introductions
            </Link>
            <Link className="button-secondary" href={`/projects/${projectId}/plan`}>
              Manage it as a project plan
            </Link>
          </div>
        }
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
        {council?.ok ? <CouncilGuide council={council.data} /> : null}
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
