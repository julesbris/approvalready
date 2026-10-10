"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { FormError } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";

/** Account page: download my data, and close my account (Milestone 19). */
export function YourData({ mfaEnabled }: { mfaEnabled: boolean }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onClose(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    const code = String(form.get("code") ?? "").trim();
    const result = await apiRequest("POST", "/auth/account/close", {
      password: String(form.get("password")),
      ...(code ? { code } : {}),
    });
    setBusy(false);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    router.replace("/");
    router.refresh();
  }

  return (
    <>
      <h3 className="subsection-title">Download your data</h3>
      <p className="muted">
        A file with your account details, sign-in history and everything in your personal
        workspace. Uploaded files are listed; download them from their projects.
      </p>
      <p>
        <a className="button button-secondary" href="/api/v1/auth/account/export" download>
          Download my data
        </a>
      </p>

      <h3 className="subsection-title">Close your account</h3>
      <p className="muted">
        You&apos;ll be signed out everywhere and your name, email and password are removed
        straight away. Within 30 days we delete your personal workspace&apos;s projects and
        files, except records the law requires us to keep. This can&apos;t be undone. Leave or
        hand over any business organisations, and cancel any plan, first.
      </p>
      <form method="post" className="form" onSubmit={onClose}>
        <label>
          Password
          <input name="password" type="password" autoComplete="current-password" required />
        </label>
        {mfaEnabled ? (
          <label>
            Code from your authenticator app (or a recovery code)
            <input name="code" autoComplete="one-time-code" required maxLength={64} />
          </label>
        ) : null}
        <label className="checkbox-label">
          <input name="confirm" type="checkbox" required />
          <span>I understand closing my account can&apos;t be undone.</span>
        </label>
        <FormError message={error} />
        <button type="submit" className="button button-danger" disabled={busy}>
          {busy ? "Closing…" : "Close my account"}
        </button>
      </form>
    </>
  );
}
