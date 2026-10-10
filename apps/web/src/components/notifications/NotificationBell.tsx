"use client";

import type { NotificationListOut } from "@approvalready/shared-types";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { apiRequest } from "@/lib/client-api";

/** "Notifications" in the header, with the unread count for the active organisation. */
export function NotificationBell({ organisationId }: { organisationId: string }) {
  const [unread, setUnread] = useState(0);
  const current = (usePathname() ?? "").startsWith("/notifications");

  useEffect(() => {
    let cancelled = false;
    apiRequest<NotificationListOut>(
      "GET",
      `/organisations/${organisationId}/notifications?unread_only=true&limit=1`,
    ).then((result) => {
      if (!cancelled && result.ok) setUnread(result.data.unread);
    });
    return () => {
      cancelled = true;
    };
  }, [organisationId]);

  return (
    <Link
      href="/notifications"
      aria-current={current ? "page" : undefined}
      aria-label={unread ? `Notifications, ${unread} unread` : undefined}
    >
      Notifications
      {unread ? (
        <span className="badge" aria-hidden="true">
          {unread > 99 ? "99+" : unread}
        </span>
      ) : null}
    </Link>
  );
}
