import type { QuietProjectOut } from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";

import { AdminNav } from "@/components/admin/AdminNav";
import { AdminNoAccess, AppShell } from "@/components/app/AppShell";
import { formatDateTime, verticalName } from "@/lib/labels";
import { QUIET_FILTERS, STAGE_LABELS, daysSince, openSummary, quietDays } from "@/lib/progress";
import { firstParam } from "@/lib/redirect";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Stuck projects", robots: { index: false } };

type Props = { searchParams: Promise<Record<string, string | string[] | undefined>> };

export default async function StuckProjectsPage({ searchParams }: Props) {
  const session = await requireSession("/admin/progress");
  if (!session.permissions.includes("platform.users.read")) {
    return (
      <AppShell session={session}>
        <AdminNoAccess what="stuck projects" session={session} />
      </AppShell>
    );
  }
  const days = quietDays(firstParam((await searchParams).days));
  const projects = orNotFound(
    await serverGet<QuietProjectOut[]>(`/admin/progress/quiet?days=${days}`),
  );
  return (
    <AppShell session={session}>
      <AdminNav current="progress" />
      <h1 className="page-title">Stuck projects</h1>
      <p className="muted">
        Open projects nobody has touched for a while that still have something to do, and where
        they stopped. Customers get up to three reminders of what&apos;s left (after a day, three
        days and a week). A personal call or email helps most with the ones still stuck after that.
      </p>
      <nav aria-label="Quiet for" className="admin-nav">
        {QUIET_FILTERS.map((d) => (
          <Link
            key={d}
            href={`/admin/progress?days=${d}`}
            aria-current={d === days ? "page" : undefined}
          >
            {d === 1 ? "Quiet 1+ day" : `Quiet ${d}+ days`}
          </Link>
        ))}
      </nav>
      {projects.length === 0 ? (
        <section className="panel empty">
          <p>No stuck projects. Everyone is moving.</p>
        </section>
      ) : (
        <div className="table-scroll">
          <table className="usage-table" aria-label="Stuck projects">
            <thead>
              <tr>
                <th>Project</th>
                <th>Customer</th>
                <th>Stopped at</th>
                <th>Still open</th>
                <th>Last active</th>
                <th>Reminders sent</th>
              </tr>
            </thead>
            <tbody>
              {projects.map((p) => (
                <tr key={p.project_id}>
                  <td>
                    <code>{p.reference_code}</code>
                    <div className="muted">{verticalName(p.vertical)}</div>
                  </td>
                  <td>
                    {p.owner_user_id ? (
                      <Link href={`/admin/accounts/${p.owner_user_id}`}>
                        {p.owner_name || p.owner_email}
                      </Link>
                    ) : (
                      "No owner"
                    )}
                    <div className="muted">{p.owner_email ?? p.organisation_name}</div>
                  </td>
                  <td>{STAGE_LABELS[p.stage] ?? p.stage}</td>
                  <td>{openSummary(p)}</td>
                  <td>
                    {formatDateTime(p.last_activity_at)}
                    <div className="muted">
                      {daysSince(p.last_activity_at) === 1
                        ? "1 day ago"
                        : `${daysSince(p.last_activity_at)} days ago`}
                    </div>
                  </td>
                  <td>
                    {p.nudges_sent}
                    {p.last_nudged_at ? (
                      <div className="muted">Last {formatDateTime(p.last_nudged_at)}</div>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </AppShell>
  );
}
