import type { BillingOut } from "@approvalready/shared-types";
import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { NoAccess } from "@/components/app/AppShell";
import { BillingPanel } from "@/components/billing/BillingPanel";
import { PartnerShell } from "@/components/partners/PartnerShell";
import { activePartnerOrganisation } from "@/lib/partners";
import { firstParam } from "@/lib/redirect";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Partner plan and billing", robots: { index: false } };

type Props = { searchParams: Promise<Record<string, string | string[] | undefined>> };

export default async function PartnerBillingPage({ searchParams }: Props) {
  const checkout = firstParam((await searchParams).checkout) ?? null;
  const session = await requireSession("/partner/billing");
  const active = activePartnerOrganisation(session);
  if (!active) redirect("/partner");
  if (!session.permissions.includes("billing.manage")) {
    return (
      <PartnerShell session={session} current="billing">
        <NoAccess what="billing" />
      </PartnerShell>
    );
  }
  const billing = orNotFound(
    await serverGet<BillingOut>(`/organisations/${active.organisation_id}/billing`),
  );
  return (
    <PartnerShell session={session} current="billing">
      <h1 className="page-title">Plan and billing</h1>
      <p className="muted">
        Your plan decides how many categories and service areas receive referrals and how many
        people can use your account. Being approved is separate: paying never skips our checks.
      </p>
      <BillingPanel organisationId={active.organisation_id} billing={billing} checkout={checkout} />
    </PartnerShell>
  );
}
