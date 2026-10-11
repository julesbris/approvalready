"use client";

import type { NewsletterStateOut } from "@approvalready/shared-types";
import Link from "next/link";
import { useEffect, useState } from "react";

import { FormError, FormNotice } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";

/**
 * What a confirmation or unsubscribe link from a guide email opens. It needs a button press,
 * because mail scanners open links in emails on their own; mail apps' own one-click
 * unsubscribe posts to the API directly.
 */
export function NewsletterLink({
  action,
  token,
}: {
  action: "confirm" | "unsubscribe";
  token: string;
}) {
  const query = `?token=${encodeURIComponent(token)}`;
  const [state, setState] = useState<NewsletterStateOut | null>(null);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void apiRequest<NewsletterStateOut>("GET", `/marketing/${action}${query}`).then((result) => {
      if (result.ok) setState(result.data);
      else setError(result.message);
    });
  }, [action, query]);

  async function go() {
    setBusy(true);
    const result =
      action === "confirm"
        ? await apiRequest<NewsletterStateOut>("POST", "/marketing/confirm", { token })
        : await apiRequest<NewsletterStateOut>("POST", `/marketing/unsubscribe${query}`);
    setBusy(false);
    if (result.ok) {
      setState(result.data);
      setDone(true);
    } else setError(result.message);
  }

  if (!state) return <FormError message={error} />;
  if (action === "confirm") {
    if (state.status === "SUBSCRIBED") {
      return (
        <FormNotice>
          {done ? "You're on the list." : "You're already on the list."} We&apos;ll send new guides
          to {state.email}. <Link href="/guides">Read the guides so far</Link>.
        </FormNotice>
      );
    }
    return (
      <div className="form">
        <p>Start getting ApprovalReady&apos;s step-by-step approval guides at {state.email}?</p>
        <FormError message={error} />
        <button type="button" className="button" onClick={go} disabled={busy}>
          Yes, send me the guides
        </button>
      </div>
    );
  }
  if (state.status !== "SUBSCRIBED") {
    return (
      <FormNotice>
        {done ? "Done." : ""} {state.email} won&apos;t get guide emails from us any more. Changed
        your mind? You can sign up again below.
      </FormNotice>
    );
  }
  return (
    <div className="form">
      <p>Stop sending guide emails to {state.email}?</p>
      <FormError message={error} />
      <button type="button" className="button" onClick={go} disabled={busy}>
        Unsubscribe
      </button>
      <p className="form-aside">Emails about your account, if you have one, still come.</p>
    </div>
  );
}
