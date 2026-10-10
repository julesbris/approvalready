import type { LeadPriceOut, StaffLeadOut } from "@approvalready/shared-types";
import type { Metadata } from "next";

import { AdminNav } from "@/components/admin/AdminNav";
import { AdminNoAccess, AppShell } from "@/components/app/AppShell";
import { LeadPrices, StaffLeads } from "@/components/leads/LeadsAdmin";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Referrals", robots: { index: false } };

export default async function LeadsAdminPage() {
  const session = await requireSession("/admin/leads");
  if (!session.permissions.includes("lead.manage")) {
    return (
      <AppShell session={session}>
        <AdminNav current="leads" />
        <AdminNoAccess what="referral settings" session={session} />
      </AppShell>
    );
  }
  const [prices, leads] = await Promise.all([
    serverGet<LeadPriceOut[]>("/admin/leads/prices"),
    serverGet<StaffLeadOut[]>("/admin/leads"),
  ]);
  return (
    <AppShell session={session}>
      <AdminNav current="leads" />
      <h1 className="page-title">Referrals</h1>
      <section className="panel" aria-labelledby="prices-title">
        <h2 id="prices-title" className="section-title">
          Referral fees
        </h2>
        <p className="muted">
          A partner pays a category&apos;s fee only after using the referrals their plan includes
          each month. A category with no fee is free. Fees never change who is matched or their
          rank. Restricted work (such as building certification) is never charged.
        </p>
        <LeadPrices prices={orNotFound(prices)} />
      </section>
      <section className="panel" aria-labelledby="leads-title">
        <h2 id="leads-title" className="section-title">
          Recent referrals
        </h2>
        <StaffLeads leads={orNotFound(leads)} />
      </section>
    </AppShell>
  );
}
