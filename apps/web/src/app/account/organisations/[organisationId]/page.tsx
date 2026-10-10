import type { InvitationOut, MemberOut, OrganisationOut } from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";

import { AppShell } from "@/components/app/AppShell";
import { OrganisationMembers } from "@/components/organisations/OrganisationMembers";
import { KIND_LABELS } from "@/lib/labels";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Organisation", robots: { index: false } };

type Props = { params: Promise<{ organisationId: string }> };

export default async function OrganisationPage({ params }: Props) {
  const { organisationId } = await params;
  const session = await requireSession(`/account/organisations/${organisationId}`);
  const base = `/organisations/${organisationId}`;
  const organisation = orNotFound(await serverGet<OrganisationOut>(base));
  const can = (permission: string) => organisation.permissions.includes(permission);
  const [members, invitations] = await Promise.all([
    can("org.members.read") ? serverGet<MemberOut[]>(`${base}/members`) : null,
    can("org.invitations.manage") ? serverGet<InvitationOut[]>(`${base}/invitations`) : null,
  ]);
  return (
    <AppShell session={session}>
      <p className="breadcrumb">
        <Link href="/account">Account</Link>
      </p>
      <h1 className="page-title">{organisation.name}</h1>
      <p className="muted">
        {KIND_LABELS[organisation.kind] ?? organisation.kind}
        {organisation.abn ? ` · ABN ${organisation.abn}` : ""}
      </p>
      {can("billing.manage") ? (
        <p>
          <Link href={`/account/organisations/${organisation.id}/billing`}>
            Billing, plans and invoices
          </Link>
        </p>
      ) : null}
      <OrganisationMembers
        organisationId={organisation.id}
        kind={organisation.kind}
        currentUserId={session.user.id}
        members={members?.ok ? members.data : []}
        invitations={invitations?.ok ? invitations.data : []}
        canManageMembers={can("org.members.manage")}
        canInvite={can("org.invitations.manage")}
      />
    </AppShell>
  );
}
