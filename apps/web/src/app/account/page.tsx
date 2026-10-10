import type { MfaStatusOut } from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";

import { ChangePasswordForm } from "@/components/account/ChangePasswordForm";
import { TwoStepSignIn } from "@/components/account/TwoStepSignIn";
import { AppShell } from "@/components/app/AppShell";
import { SignOutButtons } from "@/components/auth/SignOutButtons";
import { CreateOrganisationForm } from "@/components/organisations/CreateOrganisationForm";
import { SwitchButton } from "@/components/organisations/SwitchButton";
import { KIND_LABELS, roleList } from "@/lib/labels";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Your account", robots: { index: false } };

export default async function AccountPage() {
  const session = await requireSession("/account");
  const mfa = orNotFound(await serverGet<MfaStatusOut>("/auth/mfa"));
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

      <section className="panel" id="security" aria-labelledby="security-title">
        <h2 id="security-title" className="section-title">
          Security
        </h2>
        <h3 className="subsection-title">Two-step sign-in</h3>
        <TwoStepSignIn status={mfa} />
        <h3 className="subsection-title">Password</h3>
        <ChangePasswordForm />
      </section>

      <SignOutButtons />
    </AppShell>
  );
}
