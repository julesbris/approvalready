import type {
  AssessmentOut,
  DocumentOut,
  EvidenceOut,
  GeneratedDocumentOut,
} from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";

import { AppShell, NoAccess } from "@/components/app/AppShell";
import { AssessmentReport } from "@/components/assessments/AssessmentReport";
import { EvidencePanel } from "@/components/documents/EvidencePanel";
import { ReportDownloads } from "@/components/documents/ReportDownloads";
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
  const [found, evidence, documents, generated] = await Promise.all([
    serverGet<AssessmentOut>(`${base}/assessments/${assessmentId}`),
    serverGet<EvidenceOut[]>(`${base}/assessments/${assessmentId}/evidence`),
    serverGet<DocumentOut[]>(`${base}/projects/${projectId}/documents`),
    serverGet<GeneratedDocumentOut[]>(`${base}/projects/${projectId}/generated-documents`),
  ]);
  const assessment = orNotFound(found);
  if (assessment.project_id !== projectId) {
    orNotFound({ ok: false, status: 404 });
  }
  const canWrite = session.permissions.includes("project.write");
  return (
    <AppShell session={session}>
      <p className="breadcrumb">
        <Link href="/projects">Projects</Link> /{" "}
        <Link href={`/projects/${projectId}`}>Project</Link>
      </p>
      <AssessmentReport assessment={assessment} projectId={projectId}>
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
