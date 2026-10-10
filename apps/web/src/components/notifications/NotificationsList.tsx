"use client";

import type { NotificationListOut, NotificationOut } from "@approvalready/shared-types";
import Link from "next/link";
import { useState } from "react";

import { FormError } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";
import { formatDateTime } from "@/lib/labels";

/** The member's notifications in the active organisation, newest first. */
export function NotificationsList({
  organisationId,
  initial,
}: {
  organisationId: string;
  initial: NotificationListOut;
}) {
  const [items, setItems] = useState(initial.items);
  const [error, setError] = useState<string | null>(null);
  const base = `/organisations/${organisationId}/notifications`;
  const unread = items.filter((n) => !n.read_at).length;

  async function markRead(n: NotificationOut) {
    if (n.read_at) return;
    const result = await apiRequest<NotificationOut>("POST", `${base}/${n.id}/read`);
    if (result.ok) setItems((all) => all.map((x) => (x.id === n.id ? result.data : x)));
    else setError(result.message);
  }

  async function markAll() {
    const result = await apiRequest<{ marked: number }>("POST", `${base}/read-all`);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    const now = new Date().toISOString();
    setItems((all) => all.map((x) => (x.read_at ? x : { ...x, read_at: now })));
  }

  return (
    <section className="panel" aria-labelledby="notifications-title">
      <div className="page-head">
        <h1 id="notifications-title" className="page-title">
          Notifications
        </h1>
        {unread > 0 ? (
          <button type="button" className="button button-secondary" onClick={markAll}>
            Mark all as read
          </button>
        ) : null}
      </div>
      <FormError message={error} />
      {items.length === 0 ? (
        <p className="muted">
          Nothing yet. Reminders you set on projects, and dates in your sales and rentals, show
          up here and by email.
        </p>
      ) : null}
      <p className="muted">
        <Link href="/account#notifications">Choose which notifications you get by email</Link>
      </p>
      <ul className="notification-list">
        {items.map((n) => (
          <li key={n.id} className={n.read_at ? "notification" : "notification notification-unread"}>
            <p className="notification-title">
              {n.link_path ? (
                <Link href={n.link_path} onClick={() => markRead(n)}>
                  {n.title}
                </Link>
              ) : (
                n.title
              )}
              {!n.read_at ? <span className="badge">New</span> : null}
            </p>
            {n.body ? <p className="muted">{n.body}</p> : null}
            <p className="muted">
              {formatDateTime(n.created_at)}
              {n.email_status === "SENT" ? " · emailed" : ""}
              {!n.read_at ? (
                <>
                  {" · "}
                  <button type="button" className="button-link" onClick={() => markRead(n)}>
                    Mark as read
                  </button>
                </>
              ) : null}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}
