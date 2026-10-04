import type { Metadata } from "next";
import Link from "next/link";

import { AppShell } from "@/components/app/AppShell";
import { SignOutButtons } from "@/components/auth/SignOutButtons";
import { CreateOrganisationForm } from "@/components/organisations/CreateOrganisationForm";
import { SwitchButton } from "@/components/organisations/SwitchButton";
import { KIND_LABELS, roleList } from "@/lib/labels";
import { requireSession } from "@/lib/session";

export const metadata: Metadata = { title: "Your account", robots: { index: false } };

export default async function AccountPage() {
  const session = await requireSession("/account");
  return (
    <AppShell session={session}>
      <h1 className="page-title">Hello, {session.user.display_name}</h1>
      <p className="muted">{session.user.email}</p>

      <section className="panel" aria-labelledby="orgs-title">
        <h2 id="orgs-title" className="section-title">
          Your organisations
        </h2>
        <p className="muted">
          Projects belong to an organisation. Your personal account is one; add a business to
          work on its projects with other people.
        </p>
        <ul className="org-list" aria-label="Your organisations">
          {session.organisations.map((org) => (
            <li key={org.organisation_id} className="org-item">
              <div>
                <strong>{org.name}</strong>
                {org.organisation_id === session.active_organisation_id ? (
                  <span className="badge">Active</span>
                ) : null}
              </div>
              <div className="muted">
                {KIND_LABELS[org.kind] ?? org.kind} · {roleList(org.roles)}
              </div>
              <div className="org-actions">
                <Link href={`/account/organisations/${org.organisation_id}`}>Members and invitations</Link>
                {org.organisation_id !== session.active_organisation_id ? (
                  <SwitchButton organisationId={org.organisation_id} name={org.name} />
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section className="panel" aria-labelledby="create-org-title">
        <h2 id="create-org-title" className="section-title">
          Add a business
        </h2>
        <CreateOrganisationForm />
      </section>

      <SignOutButtons />
    </AppShell>
  );
}
