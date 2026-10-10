import type { BillingOut, OrganisationOut } from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";

import { AppShell, NoAccess } from "@/components/app/AppShell";
import { BillingPanel } from "@/components/billing/BillingPanel";
import { firstParam } from "@/lib/redirect";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Billing", robots: { index: false } };

type Props = {
  params: Promise<{ organisationId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function BillingPage({ params, searchParams }: Props) {
  const { organisationId } = await params;
  const checkout = firstParam((await searchParams).checkout) ?? null;
  const session = await requireSession(`/account/organisations/${organisationId}/billing`);
  const base = `/organisations/${organisationId}`;
  const organisation = orNotFound(await serverGet<OrganisationOut>(base));
  if (!organisation.permissions.includes("billing.manage")) {
    return (
      <AppShell session={session}>
        <NoAccess what="billing" />
      </AppShell>
    );
  }
  const billing = orNotFound(await serverGet<BillingOut>(`${base}/billing`));
  return (
    <AppShell session={session}>
      <p className="breadcrumb">
        <Link href="/account">Account</Link> /{" "}
        <Link href={`/account/organisations/${organisationId}`}>{organisation.name}</Link>
      </p>
      <h1 className="page-title">Billing</h1>
      <BillingPanel organisationId={organisationId} billing={billing} checkout={checkout} />
    </AppShell>
  );
}
