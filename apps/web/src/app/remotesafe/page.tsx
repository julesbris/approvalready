import type {
  JourneySummaryOut,
  RemoteSafeDashboardOut,
  RemoteSafeMeOut,
} from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";

import { AppShell, NoAccess } from "@/components/app/AppShell";
import {
  DashboardSummary,
  EnableRemoteSafe,
  JourneyList,
} from "@/components/remotesafe/RemoteSafeHome";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "RemoteSafe", robots: { index: false } };

export default async function RemoteSafePage() {
  const session = await requireSession("/remotesafe");
  const orgId = session.active_organisation_id;
  if (!orgId) {
    return (
      <AppShell session={session}>
        <NoAccess what="RemoteSafe" />
      </AppShell>
    );
  }
  const base = `/organisations/${orgId}/remotesafe`;
  const me = orNotFound(await serverGet<RemoteSafeMeOut>(base));
  const active = session.organisations.find((o) => o.organisation_id === orgId);
  if (!me.enabled) {
    return (
      <AppShell session={session}>
        <EnableRemoteSafe base={base} canEnable={me.org_admin && active?.kind === "BUSINESS"} />
      </AppShell>
    );
  }
  const [dashboard, mine, approvals] = await Promise.all([
    serverGet<RemoteSafeDashboardOut>(`${base}/dashboard`),
    serverGet<JourneySummaryOut[]>(`${base}/journeys`),
    me.can_approve
      ? serverGet<JourneySummaryOut[]>(`${base}/journeys?awaiting_me=true`)
      : Promise.resolve({ ok: true as const, data: [] as JourneySummaryOut[] }),
  ]);
  const journeys = mine.ok ? mine.data : [];
  const underway = journeys.filter((j) => ["ACTIVE", "OVERDUE", "ESCALATED"].includes(j.status));
  return (
    <AppShell session={session}>
      <div className="page-head">
        <h1 className="page-title">RemoteSafe</h1>
        <div className="button-row tight">
          {me.can_plan ? (
            <Link className="button" href="/remotesafe/journeys/new">
              Plan a journey
            </Link>
          ) : null}
          {me.can_administer ? (
            <Link className="button button-secondary" href="/remotesafe/admin">
              Settings
            </Link>
          ) : null}
        </div>
      </div>
      {me.roles.length === 0 && !me.org_admin ? (
        <p className="notice">
          You don&apos;t have a RemoteSafe role yet. Ask your organisation administrator to make
          you a worker, supervisor or journey monitor.
        </p>
      ) : null}
      {dashboard.ok ? <DashboardSummary d={dashboard.data} /> : null}
      {me.can_approve ? (
        <JourneyList
          title="Waiting for your approval"
          journeys={approvals.ok ? approvals.data : []}
          empty="Nothing waiting for you."
        />
      ) : null}
      {underway.length ? <JourneyList title="Underway" journeys={underway} empty="" /> : null}
      <JourneyList
        title={me.roles.includes("WHS_ADMIN") || me.org_admin ? "All journeys" : "My journeys"}
        journeys={journeys}
        empty="No journeys yet."
      />
      <section className="panel">
        <h2 className="section-title">Important</h2>
        <ul>
          {me.limitations.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      </section>
    </AppShell>
  );
}
