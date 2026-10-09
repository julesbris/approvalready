import type { ProfessionalOut } from "@approvalready/shared-types";
import type { Metadata } from "next";

import { AdminNav } from "@/components/admin/AdminNav";
import { AppShell, NoAccess } from "@/components/app/AppShell";
import { ProfessionalsAdmin } from "@/components/review/ProfessionalsAdmin";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Professionals", robots: { index: false } };

export default async function ProfessionalsPage() {
  const session = await requireSession("/admin/professionals");
  if (!session.permissions.includes("professional.verify")) {
    return (
      <AppShell session={session}>
        <NoAccess what="professional checks" />
      </AppShell>
    );
  }
  const list = orNotFound(await serverGet<ProfessionalOut[]>("/admin/professionals"));
  return (
    <AppShell session={session}>
      <AdminNav current="professionals" />
      <h1 className="page-title">Professionals</h1>
      <p className="muted">
        Check each credential against the issuer&apos;s public register (for example the Planning
        Institute of Australia or the state licensing body) before marking it checked. Only active
        professionals with a current, checked credential can be given reviews.
      </p>
      <ProfessionalsAdmin initial={list} />
    </AppShell>
  );
}
