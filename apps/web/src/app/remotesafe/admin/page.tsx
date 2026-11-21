import type {
  RemoteSafeMeOut,
  RiskPolicyOut,
  RsMemberOut,
  RsVehicleOut,
} from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";

import { AppShell, NoAccess } from "@/components/app/AppShell";
import { RemoteSafeAdmin } from "@/components/remotesafe/RemoteSafeAdmin";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "RemoteSafe settings", robots: { index: false } };

export default async function RemoteSafeAdminPage() {
  const session = await requireSession("/remotesafe/admin");
  const orgId = session.active_organisation_id;
  const base = `/organisations/${orgId}/remotesafe`;
  const me = orgId ? await serverGet<RemoteSafeMeOut>(base) : null;
  if (!orgId || !me?.ok || !me.data.enabled || !me.data.can_administer) {
    return (
      <AppShell session={session}>
        <NoAccess what="RemoteSafe settings" />
      </AppShell>
    );
  }
  const [members, vehicles, policy] = await Promise.all([
    serverGet<RsMemberOut[]>(`${base}/members`),
    serverGet<RsVehicleOut[]>(`${base}/vehicles`),
    serverGet<RiskPolicyOut>(`${base}/policy`),
  ]);
  return (
    <AppShell session={session}>
      <p className="breadcrumb">
        <Link href="/remotesafe">RemoteSafe</Link>
      </p>
      <h1 className="page-title">RemoteSafe settings</h1>
      <RemoteSafeAdmin
        base={base}
        canManageRoles={me.data.org_admin}
        tier={me.data.tier ?? "STARTER"}
        members={orNotFound(members)}
        vehicles={vehicles.ok ? vehicles.data : []}
        policy={orNotFound(policy)}
      />
    </AppShell>
  );
}
