import type { SessionOut } from "@approvalready/shared-types";
import Link from "next/link";
import type { ReactNode } from "react";

import { OrgSwitcher } from "@/components/app/OrgSwitcher";
import { defaultBrand } from "@/lib/brand";
import { activePartnerOrganisation } from "@/lib/partners";

type Section = "dashboard" | "leads" | "profile" | "billing" | "team" | "apply" | "none";

/** Layout for the partner portal (partners.<domain>, or /partner on the app host). */
export function PartnerShell({
  session,
  current = "none",
  children,
}: {
  session: SessionOut | null;
  current?: Section;
  children: ReactNode;
}) {
  const partner = session ? activePartnerOrganisation(session) : null;
  const links: [Section, string, string][] = partner
    ? [
        ["dashboard", "/partner", "Dashboard"],
        ["leads", "/partner/leads", "Referrals"],
        ["profile", "/partner/profile", "Profile"],
        ["billing", "/partner/billing", "Plan and billing"],
        ["team", `/account/organisations/${partner.organisation_id}`, "Team"],
      ]
    : [];
  return (
    <>
      <header className="site-header">
        <div className="container app-header">
          <Link className="wordmark" href="/partner">
            {defaultBrand.productName} Partners
          </Link>
          <nav aria-label="Partner" className="app-nav">
            {links.map(([key, href, label]) => (
              <Link key={key} href={href} aria-current={key === current ? "page" : undefined}>
                {label}
              </Link>
            ))}
            {session ? <Link href="/account">Account</Link> : <Link href="/login?next=/partner">Sign in</Link>}
          </nav>
          {session ? (
            <OrgSwitcher
              organisations={session.organisations}
              activeId={session.active_organisation_id ?? null}
            />
          ) : null}
        </div>
      </header>
      <main className="container app-main">{children}</main>
    </>
  );
}
