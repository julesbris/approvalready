"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { FormError } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";

/** True when the password was right and two-step sign-in wants a code next. */
function needsCode(data: unknown): boolean {
  return (data as { mfa_required?: unknown } | null)?.mfa_required === true;
}

export function LoginForm({ next }: { next: string }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [unverifiedEmail, setUnverifiedEmail] = useState<string | null>(null);
  const [resent, setResent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [codeStep, setCodeStep] = useState(false);

  function signedIn() {
    router.replace(next);
    router.refresh();
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const email = String(form.get("email"));
    setBusy(true);
    setError(null);
    const result = await apiRequest("POST", "/auth/login", {
      email,
      password: String(form.get("password")),
    });
    setBusy(false);
    if (result.ok) {
      if (needsCode(result.data)) {
        setCodeStep(true);
        return;
      }
      signedIn();
      return;
    }
    setUnverifiedEmail(result.code === "email_not_verified" ? email : null);
    setError(result.message);
  }

  async function onCode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    const result = await apiRequest("POST", "/auth/login/mfa", { code: String(form.get("code")) });
    setBusy(false);
    if (result.ok) {
      signedIn();
      return;
    }
    if (result.code === "mfa_challenge_expired") setCodeStep(false);
    setError(result.message);
  }

  async function resend() {
    if (!unverifiedEmail) return;
    await apiRequest("POST", "/auth/verify-email/resend", { email: unverifiedEmail });
    setResent(true);
  }

  if (codeStep) {
    return (
      <form method="post" className="form" onSubmit={onCode}>
        <p className="muted">
          Two-step sign-in is on. Enter the 6-digit code from your authenticator app.
        </p>
        <label>
          Code
          <input
            name="code"
            type="text"
            inputMode="numeric"
            autoComplete="one-time-code"
            minLength={6}
            maxLength={40}
            required
            autoFocus
          />
        </label>
        <p className="form-aside">
          Lost your phone? Enter one of your recovery codes instead.
        </p>
        <FormError message={error} />
        <button type="submit" className="button" disabled={busy}>
          {busy ? "Checking…" : "Continue"}
        </button>
        <button
          type="button"
          className="button-link"
          onClick={() => {
            setCodeStep(false);
            setError(null);
          }}
        >
          Start again
        </button>
      </form>
    );
  }

  return (
    <form method="post" className="form" onSubmit={onSubmit} noValidate={false}>
      <label>
        Email
        <input name="email" type="email" autoComplete="email" required />
      </label>
      <label>
        Password
        <input name="password" type="password" autoComplete="current-password" required />
      </label>
      <FormError message={error} />
      {unverifiedEmail && !resent ? (
        <button type="button" className="button-link" onClick={resend}>
          Send a new confirmation link
        </button>
      ) : null}
      {resent ? <p className="form-notice">Check your inbox for a new link.</p> : null}
      <button type="submit" className="button" disabled={busy}>
        {busy ? "Signing in…" : "Sign in"}
      </button>
      <p className="form-aside">
        <Link href="/forgot-password">Forgot your password?</Link>
      </p>
    </form>
  );
}
