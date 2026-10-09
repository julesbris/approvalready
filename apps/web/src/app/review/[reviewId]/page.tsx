import type { ReviewerWorkspaceOut } from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";

import { AppShell, NoAccess } from "@/components/app/AppShell";
import { ReviewerWorkspace } from "@/components/review/ReviewerWorkspace";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Review", robots: { index: false } };

type Props = { params: Promise<{ reviewId: string }> };

export default async function ReviewPage({ params }: Props) {
  const { reviewId } = await params;
  const session = await requireSession(`/review/${reviewId}`);
  if (!session.permissions.includes("review.perform")) {
    return (
      <AppShell session={session}>
        <NoAccess what="professional reviews" />
      </AppShell>
    );
  }
  const workspace = orNotFound(
    await serverGet<ReviewerWorkspaceOut>(`/professional/reviews/${reviewId}`),
  );
  return (
    <AppShell session={session}>
      <p className="breadcrumb">
        <Link href="/review">Reviews</Link>
      </p>
      <ReviewerWorkspace initial={workspace} />
    </AppShell>
  );
}
