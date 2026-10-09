import type {
  GrantProgramOut,
  SourceReferenceOut,
} from "@approvalready/shared-types";
import type { Metadata } from "next";

import { AdminNav } from "@/components/admin/AdminNav";
import { GrantsAdmin } from "@/components/admin/GrantsAdmin";
import { AppShell, NoAccess } from "@/components/app/AppShell";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = {
  title: "Grant programs",
  robots: { index: false },
};

export default async function GrantsAdminPage() {
  const session = await requireSession("/admin/grants");
  if (!session.permissions.includes("source.manage")) {
    return (
      <AppShell session={session}>
        <NoAccess what="grant programs" />
      </AppShell>
    );
  }
  const [programs, references] = await Promise.all([
    serverGet<GrantProgramOut[]>("/admin/grant-programs"),
    serverGet<SourceReferenceOut[]>("/admin/source-references"),
  ]);
  return (
    <AppShell session={session}>
      <AdminNav current="grants" />
      <h1 className="page-title">Grant programs</h1>
      <p className="muted">
        Customers see each program&apos;s rounds as recorded here, with the
        source you cite. When a program page changes (a round opens, closes or
        is paused), capture the page in Sources, then update the round.
        Eligibility criteria are the program&apos;s GRANT rule set in Rules.
      </p>
      <GrantsAdmin
        initial={orNotFound(programs)}
        references={orNotFound(references)}
      />
    </AppShell>
  );
}
