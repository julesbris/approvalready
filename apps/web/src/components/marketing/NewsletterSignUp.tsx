"use client";

import type { NewsletterSignUpOut } from "@approvalready/shared-types";
import { type FormEvent, useState } from "react";

import { FormError, FormNotice } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";

/** The public sign-up form for the guides email list. A confirmation email follows. */
export function NewsletterSignUp() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const result = await apiRequest<NewsletterSignUpOut>("POST", "/marketing/subscribe", {
      email,
    });
    setBusy(false);
    if (result.ok) setDone(result.data.message);
    else setError(result.message);
  }

  if (done) return <FormNotice>{done}</FormNotice>;
  return (
    <form method="post" className="form" onSubmit={onSubmit}>
      <label>
        Email address
        <input
          type="email"
          name="email"
          autoComplete="email"
          required
          maxLength={320}
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
      </label>
      <FormError message={error} />
      <button type="submit" className="button" disabled={busy}>
        Send me the guides
      </button>
      <p className="form-aside">
        We&apos;ll email you to confirm first. Every guide email has a one-click unsubscribe link,
        and we never share your address. See our <a href="/privacy">Privacy Policy</a>.
      </p>
    </form>
  );
}
