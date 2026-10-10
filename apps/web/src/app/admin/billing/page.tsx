import type { BillingStatusOut, ProductOut, StripeEventOut } from "@approvalready/shared-types";
import type { Metadata } from "next";

import { AdminNav } from "@/components/admin/AdminNav";
import { BillingAdmin } from "@/components/admin/BillingAdmin";
import { AppShell, NoAccess } from "@/components/app/AppShell";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Billing", robots: { index: false } };

export default async function BillingAdminPage() {
  const session = await requireSession("/admin/billing");
  if (!session.permissions.includes("billing.configure")) {
    return (
      <AppShell session={session}>
        <AdminNav current="billing" />
        <NoAccess what="billing settings" />
      </AppShell>
    );
  }
  const [status, products, events] = await Promise.all([
    serverGet<BillingStatusOut>("/admin/billing/status"),
    serverGet<ProductOut[]>("/admin/billing/products"),
    serverGet<StripeEventOut[]>("/admin/billing/events?limit=50"),
  ]);
  return (
    <AppShell session={session}>
      <AdminNav current="billing" />
      <h1 className="page-title">Billing</h1>
      <p className="muted">
        What can be sold comes from the reviewed catalogue in the repository; prices are set
        here. Nothing is on sale until it has a price. Payments and plans change only through
        Stripe&apos;s signed webhooks, listed below.
      </p>
      <BillingAdmin
        status={orNotFound(status)}
        products={orNotFound(products)}
        events={orNotFound(events)}
      />
    </AppShell>
  );
}
