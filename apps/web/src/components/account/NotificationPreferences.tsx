"use client";

import type { NotificationChannel, PreferencesOut } from "@approvalready/shared-types";
import { type FormEvent, useState } from "react";

import { FormError, FormNotice } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";
import { CATEGORY_LABELS, CHANNEL_LABELS, visiblePreferences } from "@/lib/notifications";

const CHANNELS = Object.keys(CHANNEL_LABELS) as NotificationChannel[];

/** Account page: choose, per category, email and in-app, in-app only, or off. */
export function NotificationPreferences({
  initial,
  isStaff,
}: {
  initial: PreferencesOut;
  isStaff: boolean;
}) {
  const [items, setItems] = useState(() => visiblePreferences(initial.items, isStaff));
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  function change(category: string, channel: NotificationChannel) {
    setSaved(false);
    setItems((all) => all.map((p) => (p.category === category ? { ...p, channel } : p)));
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const result = await apiRequest<PreferencesOut>("PUT", "/auth/notification-preferences", {
      items,
    });
    setBusy(false);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    setItems(visiblePreferences(result.data.items, isStaff));
    setSaved(true);
  }

  return (
    <form method="post" className="form" onSubmit={onSubmit}>
      {items.map((p) => (
        <label key={p.category}>
          {CATEGORY_LABELS[p.category].title}
          <span className="form-aside">{CATEGORY_LABELS[p.category].detail}</span>
          <select
            name={p.category}
            value={p.channel}
            onChange={(e) => change(p.category, e.target.value as NotificationChannel)}
          >
            {CHANNELS.map((c) => (
              <option key={c} value={c}>
                {CHANNEL_LABELS[c]}
              </option>
            ))}
          </select>
        </label>
      ))}
      <p className="form-aside">
        Emails about your account (sign-in links, password and security notices, invitations
        and professional reviews) are always sent.
      </p>
      <FormError message={error} />
      {saved ? <FormNotice>Saved.</FormNotice> : null}
      <button type="submit" className="button" disabled={busy}>
        Save notification settings
      </button>
    </form>
  );
}
