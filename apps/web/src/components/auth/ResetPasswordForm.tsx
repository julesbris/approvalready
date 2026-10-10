"use client";

import Link from "next/link";
import { type FormEvent, useState } from "react";

import { FormError, FormNotice } from "@/components/auth/FormStatus";
import { MIN_PASSWORD_LENGTH } from "@/components/auth/RegisterForm";
import { apiRequest } from "@/lib/client-api";

export function ResetPasswordForm({ token }: { token: string }) {
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const password = String(form.get("password"));
    if (password !== String(form.get("confirm"))) {
      setError("The passwords don't match.");
      return;
    }
    setBusy(true);
    const result = await apiRequest("POST", "/auth/password-reset/confirm", { token, password });
    setBusy(false);
    if (result.ok) setDone(true);
    else setError(result.message);
  }

  if (done) {
    return (
      <FormNotice>
        Your password has been changed and you&apos;ve been signed out everywhere.{" "}
        <Link href="/login">Sign in</Link>
      </FormNotice>
    );
  }
  return (
    <form method="post" className="form" onSubmit={onSubmit}>
      <label>
        New password
        <input
          name="password"
          type="password"
          autoComplete="new-password"
          required
          minLength={MIN_PASSWORD_LENGTH}
          maxLength={256}
        />
      </label>
      <label>
        Confirm new password
        <input name="confirm" type="password" autoComplete="new-password" required />
      </label>
      <FormError message={error} />
      <button type="submit" className="button" disabled={busy}>
        Set new password
      </button>
    </form>
  );
}
