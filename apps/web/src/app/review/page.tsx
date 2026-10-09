import type { ProfessionalOut, QueueItemOut } from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";

import { AppShell, NoAccess } from "@/components/app/AppShell";
import { verticalName } from "@/lib/labels";
import { formatDate } from "@/lib/questionnaire";
import { PROFESSIONAL_STATUS_LABELS, REVIEW_STATUS_LABELS } from "@/lib/review";
import { requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Reviews", robots: { index: false } };

export default async function ReviewQueuePage() {
  const session = await requireSession("/review");
  if (!session.permissions.includes("review.perform")) {
    return (
      <AppShell session={session}>
        <NoAccess what="professional reviews" />
      </AppShell>
    );
  }
  const profile = await serverGet<ProfessionalOut>("/professional/profile");
  if (!profile.ok || profile.data.status !== "ACTIVE") {
    return (
      <AppShell session={session}>
        <h1 className="page-title">Reviews</h1>
        <section className="panel">
          {profile.ok ? (
            <p>
              Your reviewer profile is{" "}
              {PROFESSIONAL_STATUS_LABELS[profile.data.status].toLowerCase()}.{" "}
              {profile.data.problems.join(" ")}
            </p>
          ) : (
            <p>Set up your reviewer profile so our team can check your credentials.</p>
          )}
          <p>
            <Link href="/review/profile">Your reviewer profile</Link>
          </p>
        </section>
      </AppShell>
    );
  }
  const queue = await serverGet<QueueItemOut[]>("/professional/reviews");
  const items = queue.ok ? queue.data : [];
  return (
    <AppShell session={session}>
      <h1 className="page-title">Reviews</h1>
      <p className="muted">
        Assessments customers asked you to check. <Link href="/review/profile">Your profile</Link>
      </p>
      {items.length === 0 ? (
        <section className="panel empty">
          <p>No reviews assigned to you.</p>
        </section>
      ) : (
        <ul className="card-list" aria-label="Your reviews">
          {items.map((r) => (
            <li key={r.id} className="card">
              <Link className="card-title" href={`/review/${r.id}`}>
                {r.project_title} ({r.project_reference})
              </Link>
              <div className="muted">
                {verticalName(r.vertical)}
                {r.due_on ? ` · due ${formatDate(r.due_on)}` : ""}
              </div>
              <span className="status">{REVIEW_STATUS_LABELS[r.status]}</span>
            </li>
          ))}
        </ul>
      )}
    </AppShell>
  );
}
