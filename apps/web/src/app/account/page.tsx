import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { AuthShell } from "@/components/AuthShell";
import { SignOutButtons } from "@/components/auth/SignOutButtons";
import { getSession } from "@/lib/session";

export const metadata: Metadata = { title: "Your account", robots: { index: false } };

const KIND_LABELS: Record<string, string> = {
  PERSONAL: "Personal account",
  BUSINESS: "Business",
  PROFESSIONAL_PRACTICE: "Professional practice",
  PARTNER: "Partner",
  PLATFORM_ADMIN: "ApprovalReady administration",
};

export default async function AccountPage() {
  const session = await getSession();
  if (!session) redirect("/login?next=/account");
  return (
    <AuthShell title={`Hello, ${session.user.display_name}`} intro={session.user.email}>
      <h2 className="section-title">Your organisations</h2>
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
              {KIND_LABELS[org.kind] ?? org.kind} · {org.roles.join(", ")}
            </div>
          </li>
        ))}
      </ul>
      <SignOutButtons />
    </AuthShell>
  );
}
