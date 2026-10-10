import type { AccountSummary } from "@approvalready/shared-types";
import type { Metadata } from "next";

import { AccountsSearch } from "@/components/admin/AccountsSearch";
import { AdminNav } from "@/components/admin/AdminNav";
import { AdminNoAccess, AppShell } from "@/components/app/AppShell";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Accounts", robots: { index: false } };

export default async function AccountsAdminPage() {
  const session = await requireSession("/admin/accounts");
  if (!session.permissions.includes("platform.users.read")) {
    return (
      <AppShell session={session}>
        <AdminNoAccess what="accounts" session={session} />
      </AppShell>
    );
  }
  const newest = orNotFound(await serverGet<AccountSummary[]>("/admin/accounts"));
  return (
    <AppShell session={session}>
      <AdminNav current="accounts" />
      <h1 className="page-title">Accounts</h1>
      <p className="muted">
        Find the person you are helping, then open their account to see their organisations, sign-in
        details and history, and to resend emails, sign them out, reset two-step sign-in or suspend
        the account. Opening an account is recorded in the audit log.
      </p>
      <AccountsSearch initial={newest} />
    </AppShell>
  );
}
