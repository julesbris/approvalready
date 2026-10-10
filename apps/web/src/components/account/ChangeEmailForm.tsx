"use client";

import type { EmailChangeOut } from "@approvalready/shared-types";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { FormError, FormNotice } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";
import { formatDateTime } from "@/lib/labels";

/**
 * Account page: change the email address (Milestone 28). A link goes to the new address;
 * the change happens when it is opened. Shows a change that is waiting, with a cancel.
 */
export function ChangeEmailForm({
  currentEmail,
  initial,
  mfaEnabled,
}: {
  currentEmail: string;
  initial: EmailChangeOut;
  mfaEnabled: boolean;
}) {
  const router = useRouter();
  const [waiting, setWaiting] = useState<EmailChangeOut>(initial);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const code = String(form.get("code") ?? "").trim();
    setBusy(true);
    setError(null);
    setNotice(null);
    const result = await apiRequest<EmailChangeOut>("POST", "/auth/email-change", {
      new_email: String(form.get("new_email")).trim(),
      password: String(form.get("password")),
      ...(code ? { code } : {}),
    });
    setBusy(false);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    formElement.reset();
    setWaiting(result.data);
    setNotice("Check the new inbox for a link to confirm the change.");
  }

  async function cancel() {
    setBusy(true);
    setError(null);
    setNotice(null);
    const result = await apiRequest<EmailChangeOut>("DELETE", "/auth/email-change");
    setBusy(false);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    setWaiting(result.data);
    setNotice("Cancelled. The link sent to the new address no longer works.");
    router.refresh();
  }

  return (
    <div className="form">
      <p className="muted">
        You sign in with <strong>{currentEmail}</strong> and we email you there.
      </p>
      {waiting.pending_email ? (
        <div className="notice" role="status">
          <p>
            Waiting for you to open the link we sent to <strong>{waiting.pending_email}</strong>
            {waiting.expires_at ? ` (it works until ${formatDateTime(waiting.expires_at)})` : ""}.
            Until then nothing changes.
          </p>
          <button
            type="button"
            className="button button-secondary"
            onClick={cancel}
            disabled={busy}
          >
            Cancel the change
          </button>
        </div>
      ) : null}
      <form method="post" className="form" onSubmit={onSubmit}>
        <label>
          New email address
          <input name="new_email" type="email" autoComplete="email" maxLength={254} required />
        </label>
        <label>
          Your password
          <input name="password" type="password" autoComplete="current-password" required />
        </label>
        {mfaEnabled ? (
          <label>
            Code from your authenticator app (or a recovery code)
            <input name="code" autoComplete="one-time-code" required maxLength={40} />
          </label>
        ) : null}
        <p className="form-aside">
          We&apos;ll send a link to the new address and let the current one know. Your address
          changes when you open the link.
        </p>
        <FormError message={error} />
        {notice ? <FormNotice>{notice}</FormNotice> : null}
        <button type="submit" className="button" disabled={busy}>
          Change email address
        </button>
      </form>
    </div>
  );
}
