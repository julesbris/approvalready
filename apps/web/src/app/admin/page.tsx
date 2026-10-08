import type { SourceReferenceOut } from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";

import { AdminNav } from "@/components/admin/AdminNav";
import { AppShell, NoAccess } from "@/components/app/AppShell";
import { VERIFICATION_LABELS } from "@/lib/assessment";
import { formatDate } from "@/lib/questionnaire";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Admin", robots: { index: false } };

export default async function AdminPage() {
  const session = await requireSession("/admin");
  if (!session.permissions.includes("source.manage")) {
    return (
      <AppShell session={session}>
        <NoAccess what="the admin area" />
      </AppShell>
    );
  }
  const queue = orNotFound(
    await serverGet<SourceReferenceOut[]>("/admin/source-references?needs_attention=true"),
  );
  return (
    <AppShell session={session}>
      <AdminNav current="home" />
      <h1 className="page-title">Review queue</h1>
      <p className="muted">
        Source references that need a reviewer: not verified yet, disputed, overdue for review,
        changed since they were verified, or no longer in force. Findings that cite them are shown
        to customers with lower confidence until they are resolved.
      </p>
      {queue.length === 0 ? (
        <section className="panel empty">
          <p>Nothing needs review.</p>
        </section>
      ) : (
        <ul className="card-list" aria-label="References needing review">
          {queue.map((ref) => (
            <li key={ref.id} className="card">
              <Link
                className="card-title"
                href={`/admin/sources/${ref.source_document_id}#ref-${ref.id}`}
              >
                {ref.citation}
              </Link>
              <div className="muted">
                {ref.attention.join(" ")}
                {ref.next_review_due ? ` Review due ${formatDate(ref.next_review_due)}.` : ""}
                {ref.rule_versions > 0 ? ` Cited by ${ref.rule_versions} rule version(s).` : ""}
              </div>
              <span className="status">{VERIFICATION_LABELS[ref.verification_status]}</span>
            </li>
          ))}
        </ul>
      )}
    </AppShell>
  );
}
