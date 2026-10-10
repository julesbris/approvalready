import type { MarketplaceCategoryOut } from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";

import { ApplyForm } from "@/components/partners/ApplyForm";
import { PartnerShell } from "@/components/partners/PartnerShell";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Apply to become a partner", robots: { index: false } };

export default async function PartnerApplyPage() {
  const session = await requireSession("/partner/apply");
  const categories = orNotFound(
    await serverGet<MarketplaceCategoryOut[]>("/marketplace/categories"),
  );
  return (
    <PartnerShell session={session} current="apply">
      <p className="breadcrumb">
        <Link href="/partner">Partners</Link>
      </p>
      <h1 className="page-title">Apply to become a partner</h1>
      <p className="muted">
        Applying creates a partner account for your business, with you as its administrator. You
        can invite your team once it is set up.
      </p>
      <ApplyForm categories={categories} />
    </PartnerShell>
  );
}
