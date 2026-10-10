import type { StaffReviewOut } from "@approvalready/shared-types";
import type { Metadata } from "next";

import { AdminNav } from "@/components/admin/AdminNav";
import { AppShell, NoAccess } from "@/components/app/AppShell";
import { AssignReview } from "@/components/review/AssignReview";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Assign a review", robots: { index: false } };

type Props = { params: Promise<{ reviewId: string }> };

export default async function AdminReviewPage({ params }: Props) {
  const { reviewId } = await params;
  const session = await requireSession(`/admin/reviews/${reviewId}`);
  if (!session.permissions.includes("review.assign")) {
    return (
      <AppShell session={session}>
        <NoAccess what="professional reviews" />
      </AppShell>
    );
  }
  const view = orNotFound(await serverGet<StaffReviewOut>(`/admin/reviews/${reviewId}`));
  return (
    <AppShell session={session}>
      <AdminNav current="reviews" />
      <AssignReview initial={view} canRefund={session.permissions.includes("billing.refund")} />
    </AppShell>
  );
}
