"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { FormError, FormNotice } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";

/** Account page: change the password (signs out other devices). */
export function ChangePasswordForm() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    setBusy(true);
    setError(null);
    setDone(false);
    const result = await apiRequest("POST", "/auth/password", {
      current_password: String(form.get("current_password")),
      new_password: String(form.get("new_password")),
    });
    setBusy(false);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    formElement.reset();
    setDone(true);
    router.refresh();
  }

  return (
    <form method="post" className="form" onSubmit={onSubmit}>
      <label>
        Current password
        <input name="current_password" type="password" autoComplete="current-password" required />
      </label>
      <label>
        New password
        <input
          name="new_password"
          type="password"
          autoComplete="new-password"
          minLength={12}
          required
        />
      </label>
      <p className="form-aside">
        At least 12 characters. Passwords found in known data breaches are refused.
      </p>
      <FormError message={error} />
      {done ? <FormNotice>Password changed. Other devices were signed out.</FormNotice> : null}
      <button type="submit" className="button" disabled={busy}>
        Change password
      </button>
    </form>
  );
}
