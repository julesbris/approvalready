import type { QueueItemOut } from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";

import { AdminNav } from "@/components/admin/AdminNav";
import { AdminNoAccess, AppShell } from "@/components/app/AppShell";
import { verticalName } from "@/lib/labels";
import { formatDate } from "@/lib/questionnaire";
import { REVIEW_STATUS_LABELS } from "@/lib/review";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Professional reviews", robots: { index: false } };

export default async function AdminReviewsPage() {
  const session = await requireSession("/admin/reviews");
  if (!session.permissions.includes("review.assign")) {
    return (
      <AppShell session={session}>
        <AdminNoAccess what="professional reviews" session={session} />
      </AppShell>
    );
  }
  const queue = orNotFound(
    await serverGet<QueueItemOut[]>(
      "/admin/reviews?status=REVIEW_REQUESTED&status=ASSIGNED&status=IN_REVIEW&status=CHANGES_REQUIRED",
    ),
  );
  // Closed reviews stay reachable, e.g. to refund one (newest first, the latest 50).
  const closed = orNotFound(
    await serverGet<QueueItemOut[]>(
      "/admin/reviews?status=CANCELLED&status=APPROVED&status=COMPLETED",
    ),
  )
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
    .slice(0, 50);
  return (
    <AppShell session={session}>
      <AdminNav current="reviews" />
      <h1 className="page-title">Professional reviews</h1>
      <p className="muted">Open review requests. Assign the ones waiting for a reviewer.</p>
      {queue.length === 0 ? (
        <section className="panel empty">
          <p>No open review requests.</p>
        </section>
      ) : (
        <ul className="card-list" aria-label="Open review requests">
          {queue.map((r) => (
            <li key={r.id} className="card">
              <Link className="card-title" href={`/admin/reviews/${r.id}`}>
                {r.project_title} ({r.project_reference})
              </Link>
              <div className="muted">
                {verticalName(r.vertical)} · requested {formatDate(r.created_at.slice(0, 10))}
                {r.due_on ? ` · due ${formatDate(r.due_on)}` : ""}
              </div>
              <span className="status">{REVIEW_STATUS_LABELS[r.status]}</span>
            </li>
          ))}
        </ul>
      )}
      {closed.length > 0 ? (
        <>
          <h2 className="section-title">Closed reviews</h2>
          <ul className="card-list" aria-label="Closed reviews">
            {closed.map((r) => (
              <li key={r.id} className="card">
                <Link className="card-title" href={`/admin/reviews/${r.id}`}>
                  {r.project_title} ({r.project_reference})
                </Link>
                <div className="muted">
                  {verticalName(r.vertical)} · requested {formatDate(r.created_at.slice(0, 10))}
                </div>
                <span className="status">{REVIEW_STATUS_LABELS[r.status]}</span>
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </AppShell>
  );
}
