import type { SessionOut } from "@approvalready/shared-types";
import Link from "next/link";
import type { ReactNode } from "react";

import { OrgSwitcher } from "@/components/app/OrgSwitcher";
import { SwitchOrganisationButton } from "@/components/app/SwitchOrganisationButton";
import { PolicyNotice } from "@/components/legal/PolicyNotice";
import { NotificationBell } from "@/components/notifications/NotificationBell";
import { SiteFooter } from "@/components/public/SiteFooter";
import { defaultBrand } from "@/lib/brand";

/** Platform staff working in the platform organisation (display only; the API decides). */
export function isStaff(session: SessionOut): boolean {
  return [
    "source.manage",
    "rule.author",
    "review.assign",
    "professional.verify",
    "partner.verify",
  ].some((p) =>
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
      <main className="container app-main">
        {session.staff_mfa_required ? (
          <p className="notice notice-warning" role="status">
            Staff pages need two-step sign-in.{" "}
            <Link href="/account#security">Turn it on in your account</Link> to use the admin
            area.
          </p>
        ) : null}
        {session.policies_to_accept?.length ? (
          <PolicyNotice policies={session.policies_to_accept} />
        ) : null}
        {children}
      </main>
      <SiteFooter />
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

/**
 * Shown on admin pages the active organisation doesn't open. Admin pages need a platform role
 * and only work while the platform organisation is active (a new sign-in starts in the personal
 * organisation), so say which of those it is and offer the switch in one click.
 */
export function AdminNoAccess({ what, session }: { what: string; session: SessionOut }) {
  const platform = session.organisations.find((o) => o.kind === "PLATFORM_ADMIN");
  if (platform && platform.organisation_id !== session.active_organisation_id) {
    const active = session.organisations.find(
      (o) => o.organisation_id === session.active_organisation_id,
    );
    return (
      <section className="panel">
        <h1 className="page-title">Switch to {platform.name} to open {what}</h1>
        <p className="muted">
          You&apos;re working in {active ? active.name : "another organisation"}. The admin pages
          only open while {platform.name} is the active organisation.
        </p>
        <SwitchOrganisationButton
          organisationId={platform.organisation_id}
          label={`Switch to ${platform.name}`}
        />
      </section>
    );
  }
  if (session.staff_mfa_required) {
    return (
      <section className="panel">
        <h1 className="page-title">Turn on two-step sign-in to open {what}</h1>
        <p className="muted">
          Staff pages need two-step sign-in.{" "}
          <Link href="/account#security">Turn it on in your account</Link>, then come back to
          this page.
        </p>
      </section>
    );
  }
  if (!platform) {
    return (
      <section className="panel">
        <h1 className="page-title">No access to {what}</h1>
        <p className="muted">
          Your account isn&apos;t on the {defaultBrand.productName} team, so it can&apos;t open
          the admin pages.
        </p>
      </section>
    );
  }
  return <NoAccess what={what} />;
}
