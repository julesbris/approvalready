import type { RemoteSafeMeOut, RsMemberOut, RsVehicleOut } from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";

import { AppShell, NoAccess } from "@/components/app/AppShell";
import { JourneyForm } from "@/components/remotesafe/JourneyForm";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Plan a journey", robots: { index: false } };

export default async function NewJourneyPage() {
  const session = await requireSession("/remotesafe/journeys/new");
  const orgId = session.active_organisation_id;
  const base = `/organisations/${orgId}/remotesafe`;
  const me = orgId ? await serverGet<RemoteSafeMeOut>(base) : null;
  if (!orgId || !me?.ok || !me.data.enabled || !me.data.can_plan) {
    return (
      <AppShell session={session}>
        <NoAccess what="journey planning" />
      </AppShell>
    );
  }
  const [members, vehicles] = await Promise.all([
    serverGet<RsMemberOut[]>(`${base}/members`),
    serverGet<RsVehicleOut[]>(`${base}/vehicles`),
  ]);
  return (
    <AppShell session={session}>
      <p className="breadcrumb">
        <Link href="/remotesafe">RemoteSafe</Link>
      </p>
      <h1 className="page-title">Plan a journey</h1>
      <p className="muted">
        Start with the basics. Next you add route legs and check-ins, then see the risk
        assessment and the pre-departure checklist.
      </p>
      <section className="panel">
        <JourneyForm
          base={base}
          members={orNotFound(members)}
          vehicles={vehicles.ok ? vehicles.data : []}
          timezones={me.data.timezones}
          defaultTimezone={me.data.default_timezone}
          meId={session.user.id}
          canPlanForOthers={me.data.roles.some((r) => r === "SUPERVISOR" || r === "WHS_ADMIN")}
        />
      </section>
    </AppShell>
  );
}
