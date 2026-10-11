"use client";

import type { AccountNewsletterOut } from "@approvalready/shared-types";
import { useState } from "react";

import { FormError, FormNotice } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";

/** Account page: join or leave the guides email list (no confirmation email needed). */
export function GuidesByEmail({ initial }: { initial: boolean }) {
  const [subscribed, setSubscribed] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function change(next: boolean) {
    setBusy(true);
    setError(null);
    setSaved(false);
    const result = await apiRequest<AccountNewsletterOut>("PUT", "/auth/newsletter", {
      subscribed: next,
    });
    setBusy(false);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    setSubscribed(result.data.subscribed);
    setSaved(true);
  }

  return (
    <div className="form">
      <label className="checkbox-label">
        <input
          type="checkbox"
          checked={subscribed}
          disabled={busy}
          onChange={(e) => change(e.target.checked)}
        />
        Send me new step-by-step approval guides by email
      </label>
      <FormError message={error} />
      {saved ? (
        <FormNotice>{subscribed ? "You're on the list." : "You're off the list."}</FormNotice>
      ) : null}
    </div>
  );
}
