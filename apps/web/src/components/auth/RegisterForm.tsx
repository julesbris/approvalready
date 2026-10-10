"use client";

import { type FormEvent, useState } from "react";

import { FormError, FormNotice } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";

export const MIN_PASSWORD_LENGTH = 12;

export function RegisterForm() {
  const [error, setError] = useState<string | null>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const email = String(form.get("email"));
    setBusy(true);
    setError(null);
    const result = await apiRequest("POST", "/auth/register", {
      display_name: String(form.get("display_name")),
      email,
      password: String(form.get("password")),
    });
    setBusy(false);
    if (result.ok) setSentTo(email);
    else setError(result.message);
  }

  if (sentTo) {
    return (
      <FormNotice>
        We sent a confirmation link to <strong>{sentTo}</strong>. Open it to finish creating your
        account.
      </FormNotice>
    );
  }

  return (
    <form method="post" className="form" onSubmit={onSubmit}>
      <label>
        Your name
        <input name="display_name" autoComplete="name" required maxLength={120} />
      </label>
      <label>
        Email
        <input name="email" type="email" autoComplete="email" required />
      </label>
      <label>
        Password
        <input
          name="password"
          type="password"
          autoComplete="new-password"
          required
          minLength={MIN_PASSWORD_LENGTH}
          maxLength={256}
          aria-describedby="password-hint"
        />
        <span id="password-hint" className="hint">
          At least {MIN_PASSWORD_LENGTH} characters. A short phrase works well.
        </span>
      </label>
      <FormError message={error} />
      <button type="submit" className="button" disabled={busy}>
        {busy ? "Creating account…" : "Create account"}
      </button>
    </form>
  );
}
