import type { MarketplaceCategoryOut, PartnerOut } from "@approvalready/shared-types";
import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { PartnerProfile } from "@/components/partners/PartnerProfile";
import { PartnerShell } from "@/components/partners/PartnerShell";
import { activePartnerOrganisation } from "@/lib/partners";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Partner profile", robots: { index: false } };

export default async function PartnerProfilePage() {
  const session = await requireSession("/partner/profile");
  const active = activePartnerOrganisation(session);
  if (!active) redirect("/partner");
  const [partner, categories] = await Promise.all([
    serverGet<PartnerOut>(`/organisations/${active.organisation_id}/partner`),
    serverGet<MarketplaceCategoryOut[]>("/marketplace/categories"),
  ]);
  return (
    <PartnerShell session={session} current="profile">
      <h1 className="page-title">Partner profile</h1>
      <PartnerProfile
        organisationId={active.organisation_id}
        initial={orNotFound(partner)}
        categories={orNotFound(categories)}
        canManage={session.permissions.includes("partner.manage")}
      />
    </PartnerShell>
  );
}
