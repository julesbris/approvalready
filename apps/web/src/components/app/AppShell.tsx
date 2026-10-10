import type { SessionOut } from "@approvalready/shared-types";
import Link from "next/link";
import type { ReactNode } from "react";

import { OrgSwitcher } from "@/components/app/OrgSwitcher";
import { NotificationBell } from "@/components/notifications/NotificationBell";
import { defaultBrand } from "@/lib/brand";

/** Platform staff working in the platform organisation (display only; the API decides). */
export function isStaff(session: SessionOut): boolean {
  return ["source.manage", "rule.author", "review.assign", "professional.verify"].some((p) =>
    session.permissions.includes(p),
  );
}

/** Layout for signed-in pages: header with navigation and the active-organisation switcher. */
export function AppShell({
  session,
  children,
}: {
  session: SessionOut;
  children: ReactNode;
}) {
  return (
    <>
      <header className="site-header">
        <div className="container app-header">
          <Link className="wordmark" href="/projects">
            {defaultBrand.productName}
          </Link>
          <nav aria-label="Main" className="app-nav">
            <Link href="/projects">Projects</Link>
            {session.permissions.includes("review.perform") ? (
              <Link href="/review">Reviews</Link>
            ) : null}
            {session.active_organisation_id ? (
              <NotificationBell organisationId={session.active_organisation_id} />
            ) : null}
            <Link href="/account">Account</Link>
            {isStaff(session) ? <Link href="/admin">Admin</Link> : null}
          </nav>
          <OrgSwitcher
            organisations={session.organisations}
            activeId={session.active_organisation_id ?? null}
          />
        </div>
      </header>
      <main className="container app-main">{children}</main>
    </>
  );
}

/** Shown when the active organisation doesn't give access to a page. */
export function NoAccess({ what }: { what: string }) {
  return (
    <section className="panel">
      <h1 className="page-title">No access to {what}</h1>
      <p className="muted">
        Your role in the active organisation doesn&apos;t include {what}. Switch organisation
        above, or ask an administrator of this organisation to change your role.
      </p>
    </section>
  );
}
