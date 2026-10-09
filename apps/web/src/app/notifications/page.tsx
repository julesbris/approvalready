import type { NotificationListOut } from "@approvalready/shared-types";
import type { Metadata } from "next";

import { AppShell } from "@/components/app/AppShell";
import { NotificationsList } from "@/components/notifications/NotificationsList";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Notifications", robots: { index: false } };

export default async function NotificationsPage() {
  const session = await requireSession("/notifications");
  const orgId = session.active_organisation_id;
  if (!orgId) {
    return (
      <AppShell session={session}>
        <p>Choose an organisation to see its notifications.</p>
      </AppShell>
    );
  }
  const list = orNotFound(await serverGet<NotificationListOut>(`/organisations/${orgId}/notifications`));
  return (
    <AppShell session={session}>
      <NotificationsList organisationId={orgId} initial={list} />
    </AppShell>
  );
}
