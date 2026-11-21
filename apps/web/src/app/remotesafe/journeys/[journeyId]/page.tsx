import type {
  ControlCheckOut,
  JourneyAssessmentOut,
  JourneyEventOut,
  JourneyOut,
  RemoteSafeMeOut,
  RsMemberOut,
  RsVehicleOut,
} from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";

import { AppShell, NoAccess } from "@/components/app/AppShell";
import { JourneyWorkspace } from "@/components/remotesafe/JourneyWorkspace";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Journey", robots: { index: false } };

type Props = { params: Promise<{ journeyId: string }> };

export default async function JourneyPage({ params }: Props) {
  const { journeyId } = await params;
  const session = await requireSession(`/remotesafe/journeys/${journeyId}`);
  const orgId = session.active_organisation_id;
  if (!orgId) {
    return (
      <AppShell session={session}>
        <NoAccess what="RemoteSafe" />
      </AppShell>
    );
  }
  const base = `/organisations/${orgId}/remotesafe`;
  const url = `${base}/journeys/${journeyId}`;
  const [me, journey, assessment, controls, events, members, vehicles] = await Promise.all([
    serverGet<RemoteSafeMeOut>(base),
    serverGet<JourneyOut>(url),
    serverGet<JourneyAssessmentOut>(`${url}/assessment`),
    serverGet<ControlCheckOut[]>(`${url}/controls`),
    serverGet<JourneyEventOut[]>(`${url}/events`),
    serverGet<RsMemberOut[]>(`${base}/members`),
    serverGet<RsVehicleOut[]>(`${base}/vehicles`),
  ]);
  const found = orNotFound(journey);
  const about = orNotFound(me);
  return (
    <AppShell session={session}>
      <p className="breadcrumb">
        <Link href="/remotesafe">RemoteSafe</Link> / {found.reference}
      </p>
      <JourneyWorkspace
        base={base}
        meId={session.user.id}
        isWhsAdmin={about.roles.includes("WHS_ADMIN")}
        journey={found}
        assessment={orNotFound(assessment)}
        controls={controls.ok ? controls.data : []}
        events={events.ok ? events.data : []}
        members={members.ok ? members.data : []}
        vehicles={vehicles.ok ? vehicles.data : []}
        timezones={about.timezones}
        limitations={about.limitations}
      />
    </AppShell>
  );
}
