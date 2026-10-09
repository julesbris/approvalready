import type { ProfessionalOut } from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";

import { AppShell, NoAccess } from "@/components/app/AppShell";
import { ProfileEditor } from "@/components/review/ProfileEditor";
import { requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Reviewer profile", robots: { index: false } };

export default async function ReviewerProfilePage() {
  const session = await requireSession("/review/profile");
  if (!session.permissions.includes("review.perform")) {
    return (
      <AppShell session={session}>
        <NoAccess what="professional reviews" />
      </AppShell>
    );
  }
  const profile = await serverGet<ProfessionalOut>("/professional/profile");
  if (!profile.ok && profile.status !== 404) {
    throw new Error(`API request failed (${profile.status})`);
  }
  return (
    <AppShell session={session}>
      <p className="breadcrumb">
        <Link href="/review">Reviews</Link>
      </p>
      <h1 className="page-title">Reviewer profile</h1>
      <ProfileEditor initial={profile.ok ? profile.data : null} />
    </AppShell>
  );
}
