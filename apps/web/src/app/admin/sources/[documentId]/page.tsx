import type {
  SnapshotSummary,
  SourceDocumentOut,
  SourceReferenceOut,
} from "@approvalready/shared-types";
import type { Metadata } from "next";

import { AdminNav } from "@/components/admin/AdminNav";
import { DocumentWorkspace } from "@/components/admin/DocumentWorkspace";
import { AdminNoAccess, AppShell } from "@/components/app/AppShell";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = {
  title: "Source document",
  robots: { index: false },
};

export default async function SourceDocumentPage({
  params,
}: {
  params: Promise<{ documentId: string }>;
}) {
  const { documentId } = await params;
  const session = await requireSession(`/admin/sources/${documentId}`);
  if (!session.permissions.includes("source.manage")) {
    return (
      <AppShell session={session}>
        <AdminNoAccess what="the admin area" session={session} />
      </AppShell>
    );
  }
  const id = encodeURIComponent(documentId);
  const [document, snapshots, references] = await Promise.all([
    serverGet<SourceDocumentOut>(`/admin/source-documents/${id}`),
    serverGet<SnapshotSummary[]>(`/admin/source-documents/${id}/snapshots`),
    serverGet<SourceReferenceOut[]>(`/admin/source-references?source_document_id=${id}`),
  ]);
  return (
    <AppShell session={session}>
      <AdminNav current="sources" />
      <DocumentWorkspace
        document={orNotFound(document)}
        snapshots={orNotFound(snapshots)}
        references={orNotFound(references)}
        canVerify={session.permissions.includes("source.verify")}
      />
    </AppShell>
  );
}
