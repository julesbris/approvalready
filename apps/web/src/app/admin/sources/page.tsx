import type {
  SourceDocumentOut,
  SourceOrganisationOut,
} from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";

import { AdminNav } from "@/components/admin/AdminNav";
import { RereadUnreadable } from "@/components/admin/RereadUnreadable";
import { SOURCE_TYPES, SourceForms } from "@/components/admin/SourceForms";
import { AdminNoAccess, AppShell } from "@/components/app/AppShell";
import { VERIFICATION_LABELS } from "@/lib/assessment";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = {
  title: "Sources",
  robots: { index: false },
};

const FILE_OUTCOMES = ["FILE_SEEN", "FILE_CHANGED", "FILE_UNCHANGED"];

function unreadable(d: SourceDocumentOut): boolean {
  const outcome = d.last_check?.outcome;
  return (
    d.auto_check &&
    (outcome === "FAILED" || FILE_OUTCOMES.includes(outcome ?? ""))
  );
}

function sourceStatus(d: SourceDocumentOut): string {
  const check = d.last_check;
  if (check?.outcome === "FAILED") return "Couldn't be read";
  if (FILE_OUTCOMES.includes(check?.outcome ?? "")) return "File without text";
  if (check?.outcome === "CHANGED" || check?.outcome === "FILE_CHANGED")
    return "Changed";
  return d.latest_snapshot ? "Snapshot taken" : "No snapshot";
}

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
  const notRead = docs.filter(unreadable).length;
  return (
    <AppShell session={session}>
      <AdminNav current="sources" />
      <h1 className="page-title">Sources</h1>
      <p className="muted">
        Every rule must cite the official source it encodes. Record each
        document with its official address, version and dates. Every Monday the
        app reads each address (web pages and PDFs) and saves a snapshot when
        the wording changes. Sites that turn the app away are asked a second
        time the way a browser asks.
      </p>
      {notRead > 0 ? (
        <section className="panel">
          <p>
            {notRead} source{notRead === 1 ? "" : "s"} couldn&apos;t be read
            last time. The app now reads PDFs and retries sites that turned it
            away, so try them again. Any still unreadable after that need their
            text pasted by hand.
          </p>
          <RereadUnreadable count={notRead} />
        </section>
      ) : null}
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
                {d.organisation_name} · {SOURCE_TYPES[d.source_type]} ·{" "}
                {d.jurisdiction}
                {d.version_label ? ` · ${d.version_label}` : ""} ·{" "}
                {Object.entries(d.reference_counts)
                  .map(
                    ([status, n]) =>
                      `${n} ${VERIFICATION_LABELS[status]?.toLowerCase()}`,
                  )
                  .join(", ") || "no references"}
              </div>
              <span className="status">{sourceStatus(d)}</span>
            </li>
          ))}
        </ul>
      )}
      <SourceForms organisations={orNotFound(organisations)} />
    </AppShell>
  );
}
