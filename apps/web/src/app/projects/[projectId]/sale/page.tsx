import type {
  DocumentOut,
  EnquiryOut,
  OfferOut,
  ProjectDetailOut,
  SaleDocumentOut,
  SaleOut,
} from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";

import { AppShell, NoAccess } from "@/components/app/AppShell";
import { SaleWorkspace } from "@/components/property/SaleWorkspace";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Your sale", robots: { index: false } };

type Props = { params: Promise<{ projectId: string }> };

export default async function SalePage({ params }: Props) {
  const { projectId } = await params;
  const session = await requireSession(`/projects/${projectId}/sale`);
  const orgId = session.active_organisation_id;
  if (!orgId || !session.permissions.includes("project.read")) {
    return (
      <AppShell session={session}>
        <NoAccess what="projects" />
      </AppShell>
    );
  }
  const base = `/organisations/${orgId}/projects/${projectId}`;
  const [project, sale, vault, offers, enquiries, documents] = await Promise.all([
    serverGet<ProjectDetailOut>(base),
    serverGet<SaleOut>(`${base}/sale`),
    serverGet<SaleDocumentOut[]>(`${base}/sale/documents`),
    serverGet<OfferOut[]>(`${base}/sale/offers`),
    serverGet<EnquiryOut[]>(`${base}/sale/enquiries`),
    serverGet<DocumentOut[]>(`${base}/documents`),
  ]);
  const found = orNotFound(project);
  return (
    <AppShell session={session}>
      <p className="breadcrumb">
        <Link href="/projects">Projects</Link> /{" "}
        <Link href={`/projects/${projectId}`}>{found.title}</Link>
      </p>
      {sale.ok ? (
        <SaleWorkspace
          organisationId={orgId}
          projectId={projectId}
          projectTitle={found.title}
          sale={sale.data}
          vault={vault.ok ? vault.data : []}
          offers={offers.ok ? offers.data : []}
          enquiries={enquiries.ok ? enquiries.data : []}
          projectDocuments={documents.ok ? documents.data : []}
          canWrite={session.permissions.includes("project.write")}
        />
      ) : (
        <p>A sale belongs to a selling project.</p>
      )}
    </AppShell>
  );
}
