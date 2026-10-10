"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { FormError } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";

export function LoginForm({ next }: { next: string }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [unverifiedEmail, setUnverifiedEmail] = useState<string | null>(null);
  const [resent, setResent] = useState(false);
  const [busy, setBusy] = useState(false);

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
      router.replace(next);
      router.refresh();
      return;
    }
    setUnverifiedEmail(result.code === "email_not_verified" ? email : null);
    setError(result.message);
  }

  async function resend() {
    if (!unverifiedEmail) return;
    await apiRequest("POST", "/auth/verify-email/resend", { email: unverifiedEmail });
    setResent(true);
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
