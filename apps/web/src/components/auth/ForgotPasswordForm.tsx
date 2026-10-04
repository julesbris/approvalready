"use client";

import { type FormEvent, useState } from "react";

import { FormError, FormNotice } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";

export function ForgotPasswordForm() {
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    const result = await apiRequest("POST", "/auth/password-reset/request", {
      email: String(form.get("email")),
    });
    setBusy(false);
    if (result.ok) setSent(true);
    else setError(result.message);
  }

  if (sent) {
    return (
      <FormNotice>
        If an account exists for that address, we&apos;ve emailed a link to reset your password.
      </FormNotice>
    );
  }
  return (
    <form className="form" onSubmit={onSubmit}>
      <label>
        Email
        <input name="email" type="email" autoComplete="email" required />
      </label>
      <FormError message={error} />
      <button type="submit" className="button" disabled={busy}>
        Send reset link
      </button>
    </form>
  );
}
