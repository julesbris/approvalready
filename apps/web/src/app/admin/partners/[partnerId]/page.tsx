import type { CreditStaffOut, StaffPartnerOut } from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";

import { AdminNav } from "@/components/admin/AdminNav";
import { AdminNoAccess, AppShell } from "@/components/app/AppShell";
import { PartnerCredits } from "@/components/leads/LeadsAdmin";
import { PartnerReview } from "@/components/partners/PartnerReview";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Partner", robots: { index: false } };

type Props = { params: Promise<{ partnerId: string }> };

export default async function PartnerAdminPage({ params }: Props) {
  const { partnerId } = await params;
  const session = await requireSession(`/admin/partners/${partnerId}`);
  if (!session.permissions.includes("partner.verify")) {
    return (
      <AppShell session={session}>
        <AdminNoAccess what="partner checks" session={session} />
      </AppShell>
    );
  }
  const partner = orNotFound(await serverGet<StaffPartnerOut>(`/admin/partners/${partnerId}`));
  const credits = session.permissions.includes("lead.manage")
    ? await serverGet<CreditStaffOut>(`/admin/leads/partners/${partnerId}/credits`)
    : null;
  return (
    <AppShell session={session}>
      <AdminNav current="partners" />
      <p className="breadcrumb">
        <Link href="/admin/partners">Partners</Link>
      </p>
      <PartnerReview initial={partner} />
      {credits && credits.ok ? <PartnerCredits initial={credits.data} /> : null}
    </AppShell>
  );
}
