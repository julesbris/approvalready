import type { SourceDocumentOut, SourceOrganisationOut } from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";

import { AdminNav } from "@/components/admin/AdminNav";
import { SOURCE_TYPES, SourceForms } from "@/components/admin/SourceForms";
import { AdminNoAccess, AppShell } from "@/components/app/AppShell";
import { VERIFICATION_LABELS } from "@/lib/assessment";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = {
  title: "Sources",
  robots: { index: false },
};

export default async function SourcesPage() {
  const session = await requireSession("/admin/sources");
  if (!session.permissions.includes("source.manage")) {
    return (
      <AppShell session={session}>
        <AdminNoAccess what="the admin area" session={session} />
      </AppShell>
    );
  }
  const [documents, organisations] = await Promise.all([
    serverGet<SourceDocumentOut[]>("/admin/source-documents"),
    serverGet<SourceOrganisationOut[]>("/admin/source-organisations"),
  ]);
  const docs = orNotFound(documents);
  return (
    <AppShell session={session}>
      <AdminNav current="sources" />
      <h1 className="page-title">Sources</h1>
      <p className="muted">
        Every rule must cite the official source it encodes. Capture each document by hand from its
        official address, with its version and dates; nothing here is fetched from a government
        system.
      </p>
      {docs.length === 0 ? (
        <section className="panel empty">
          <p>No source documents yet.</p>
        </section>
      ) : (
        <ul className="card-list" aria-label="Source documents">
          {docs.map((d) => (
            <li key={d.id} className="card">
              <Link className="card-title" href={`/admin/sources/${d.id}`}>
                {d.title}
              </Link>
              <div className="muted">
                {d.organisation_name} · {SOURCE_TYPES[d.source_type]} · {d.jurisdiction}
                {d.version_label ? ` · ${d.version_label}` : ""} ·{" "}
                {Object.entries(d.reference_counts)
                  .map(([status, n]) => `${n} ${VERIFICATION_LABELS[status]?.toLowerCase()}`)
                  .join(", ") || "no references"}
              </div>
              <span className="status">{d.latest_snapshot ? "Snapshot taken" : "No snapshot"}</span>
            </li>
          ))}
        </ul>
      )}
      <SourceForms organisations={orNotFound(organisations)} />
    </AppShell>
  );
}
