import type { OpsStatusOut } from "@approvalready/shared-types";
import type { Metadata } from "next";

import { AdminNav } from "@/components/admin/AdminNav";
import { OpsStatus } from "@/components/admin/OpsStatus";
import { AppShell, NoAccess } from "@/components/app/AppShell";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Operations", robots: { index: false } };

export default async function OpsAdminPage() {
  const session = await requireSession("/admin/ops");
  if (!session.permissions.includes("platform.audit.read")) {
    return (
      <AppShell session={session}>
        <NoAccess what="operations" />
      </AppShell>
    );
  }
  const status = orNotFound(await serverGet<OpsStatusOut>("/admin/ops"));
  return (
    <AppShell session={session}>
      <AdminNav current="ops" />
      <h1 className="page-title">Operations</h1>
      <p className="muted">
        Is the platform looking after itself: background jobs, nightly backups, the weekly
        restore check, off-site copies and disk space.
      </p>
      <OpsStatus status={status} />
    </AppShell>
  );
}
