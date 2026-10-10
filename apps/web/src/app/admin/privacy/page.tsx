import type { PrivacyRequestOut } from "@approvalready/shared-types";
import type { Metadata } from "next";

import { AdminNav } from "@/components/admin/AdminNav";
import { PrivacyRequests } from "@/components/admin/PrivacyRequests";
import { AppShell, NoAccess } from "@/components/app/AppShell";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Privacy requests", robots: { index: false } };

export default async function PrivacyAdminPage() {
  const session = await requireSession("/admin/privacy");
  if (!session.permissions.includes("privacy.manage")) {
    return (
      <AppShell session={session}>
        <NoAccess what="privacy requests" />
      </AppShell>
    );
  }
  const requests = orNotFound(await serverGet<PrivacyRequestOut[]>("/admin/privacy/requests"));
  return (
    <AppShell session={session}>
      <AdminNav current="privacy" />
      <h1 className="page-title">Privacy requests</h1>
      <p className="muted">
        Requests to see, correct or delete personal information, complaints, and accounts
        their owners closed. The Australian Privacy Principles expect an answer within 30 days;
        Operations shows a warning while any are open and an alert once one is overdue. For a
        closed account, delete the personal workspace&apos;s projects and files (keep payment
        records), then email the person and mark the request done.
      </p>
      <PrivacyRequests requests={requests} />
    </AppShell>
  );
}
