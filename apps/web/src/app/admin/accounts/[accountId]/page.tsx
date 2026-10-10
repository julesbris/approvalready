import type { AccountDetail } from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";

import { AccountActions } from "@/components/admin/AccountActions";
import { AdminNav } from "@/components/admin/AdminNav";
import { AdminNoAccess, AppShell } from "@/components/app/AppShell";
import { accountState, describeDevice, eventBy, eventLabel } from "@/lib/accounts";
import { formatDateTime, KIND_LABELS, ROLE_LABELS, roleList } from "@/lib/labels";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Account", robots: { index: false } };

type Props = { params: Promise<{ accountId: string }> };

const SURFACE_LABELS: Record<string, string> = {
  app: "App",
  partners: "Partner portal",
  review: "Reviewer workspace",
  public: "Website",
};

export default async function AccountAdminPage({ params }: Props) {
  const { accountId } = await params;
  const session = await requireSession(`/admin/accounts/${accountId}`);
  if (!session.permissions.includes("platform.users.read")) {
    return (
      <AppShell session={session}>
        <AdminNoAccess what="accounts" session={session} />
      </AppShell>
    );
  }
  const account = orNotFound(await serverGet<AccountDetail>(`/admin/accounts/${accountId}`));
  const self = account.id === session.user.id;
  return (
    <AppShell session={session}>
      <AdminNav current="accounts" />
      <p className="breadcrumb">
        <Link href="/admin/accounts">Accounts</Link>
      </p>
      <div className="page-head">
        <h1 className="page-title">{account.display_name}</h1>
        <span className="status">{accountState(account)}</span>
      </div>

      <section className="panel">
        <dl className="facts">
          <dt>Email</dt>
          <dd>
            {account.closed ? (
              account.email
            ) : (
              <a href={`mailto:${account.email}`}>{account.email}</a>
            )}
            {account.email_verified ? "" : " (not confirmed yet)"}
          </dd>
          <dt>Joined</dt>
          <dd>{formatDateTime(account.created_at)}</dd>
          <dt>Last signed in</dt>
          <dd>{account.last_login_at ? formatDateTime(account.last_login_at) : "Never"}</dd>
          <dt>Password</dt>
          <dd>
            {account.password_set
              ? account.password_changed_at
                ? `Set, last changed ${formatDateTime(account.password_changed_at)}`
                : "Set"
              : "None"}
          </dd>
          <dt>Two-step sign-in</dt>
          <dd>
            {account.mfa_enabled
              ? `On (${account.recovery_codes_left} recovery code${
                  account.recovery_codes_left === 1 ? "" : "s"
                } left)`
              : "Off"}
          </dd>
          <dt>Staff role</dt>
          <dd>
            {account.platform_role
              ? (ROLE_LABELS[account.platform_role] ?? account.platform_role)
              : "None"}
          </dd>
          <dt>Account id</dt>
          <dd>
            <code>{account.id}</code>
          </dd>
        </dl>
      </section>

      <section className="panel">
        <h2 className="section-title">Help this person</h2>
        {self ? (
          <p className="muted">
            This is your own account: use <Link href="/account">Account</Link> instead.
          </p>
        ) : account.closed ? (
          <p className="muted">
            The owner closed this account. Its personal details have been removed; see Privacy for
            the deletion request.
          </p>
        ) : !session.permissions.includes("platform.users.manage") ? (
          <p className="muted">
            You can look but not change accounts. Ask a platform administrator.
          </p>
        ) : account.platform_role && !session.permissions.includes("platform.roles.manage") ? (
          <p className="muted">
            Only a super administrator can change a staff member&apos;s account.
          </p>
        ) : (
          <AccountActions accountId={account.id} actions={account.allowed_actions} />
        )}
      </section>

      <section className="panel">
        <h2 className="section-title">Organisations</h2>
        {account.memberships.length === 0 ? (
          <p className="muted">None.</p>
        ) : (
          <table className="usage-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Kind</th>
                <th>Their roles</th>
                <th>Since</th>
              </tr>
            </thead>
            <tbody>
              {account.memberships.map((m) => (
                <tr key={m.organisation_id}>
                  <td>
                    {m.name}
                    {m.abn ? <span className="muted"> · ABN {m.abn}</span> : null}
                    {m.organisation_status !== "ACTIVE" ? (
                      <span className="badge">Organisation suspended</span>
                    ) : null}
                    {m.member_status !== "ACTIVE" ? (
                      <span className="badge">No longer a member</span>
                    ) : null}
                  </td>
                  <td>{KIND_LABELS[m.kind] ?? m.kind}</td>
                  <td>{roleList(m.roles)}</td>
                  <td>{formatDateTime(m.joined_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="panel">
        <h2 className="section-title">Signed in now</h2>
        {account.sessions.length === 0 ? (
          <p className="muted">Not signed in anywhere.</p>
        ) : (
          <table className="usage-table">
            <thead>
              <tr>
                <th>Device</th>
                <th>Where</th>
                <th>Signed in</th>
                <th>Last seen</th>
              </tr>
            </thead>
            <tbody>
              {account.sessions.map((s) => (
                <tr key={s.id}>
                  <td>{describeDevice(s.user_agent)}</td>
                  <td>
                    {SURFACE_LABELS[s.surface] ?? s.surface}
                    {s.ip ? <span className="muted"> · {s.ip}</span> : null}
                  </td>
                  <td>{formatDateTime(s.created_at)}</td>
                  <td>{formatDateTime(s.last_seen_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="panel">
        <h2 className="section-title">Recent history</h2>
        {account.events.length === 0 ? (
          <p className="muted">Nothing recorded.</p>
        ) : (
          <table className="usage-table">
            <thead>
              <tr>
                <th>When</th>
                <th>What</th>
                <th>By</th>
              </tr>
            </thead>
            <tbody>
              {account.events.map((e) => (
                <tr key={e.seq}>
                  <td>{formatDateTime(e.occurred_at)}</td>
                  <td>
                    {eventLabel(e.action)}
                    {typeof e.details.reason === "string" ? (
                      <span className="muted"> · {e.details.reason}</span>
                    ) : null}
                  </td>
                  <td>{eventBy(e)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </AppShell>
  );
}
