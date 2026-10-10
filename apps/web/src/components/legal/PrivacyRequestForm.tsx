"use client";

import type { PrivacyRequestCreated } from "@approvalready/shared-types";
import { type FormEvent, useState } from "react";

import { FormError, FormNotice } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";
import { formatDate } from "@/lib/questionnaire";
import { PRIVACY_REQUEST_KINDS } from "@/lib/legal";

/** Contact page: a privacy request (access, correction, deletion, complaint). */
export function PrivacyRequestForm() {
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<PrivacyRequestCreated | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    const result = await apiRequest<PrivacyRequestCreated>("POST", "/privacy/requests", {
      name: String(form.get("name")),
      email: String(form.get("email")),
      kind: String(form.get("kind")),
      details: String(form.get("details")),
    });
    setBusy(false);
    if (result.ok) setCreated(result.data);
    else setError(result.message);
  }

  if (created) {
    return (
      <FormNotice>
        Thanks. Your reference is <strong>{created.reference}</strong>. We will reply by email
        by {formatDate(created.due_at.slice(0, 10))}.
      </FormNotice>
    );
  }

  return (
    <form method="post" className="form" onSubmit={onSubmit}>
      <label>
        Your name
        <input name="name" autoComplete="name" required maxLength={120} />
      </label>
      <label>
        Email
        <input name="email" type="email" autoComplete="email" required />
      </label>
      <label>
        What would you like?
        <select name="kind" required defaultValue="ACCESS">
          {PRIVACY_REQUEST_KINDS.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <label>
        Details
        <textarea name="details" required minLength={10} maxLength={4000} rows={5} />
        <span className="hint">
          Use the email address of your account so we can find it. Don&apos;t include
          passwords.
        </span>
      </label>
      <FormError message={error} />
      <button type="submit" className="button" disabled={busy}>
        {busy ? "Sending…" : "Send"}
      </button>
    </form>
  );
}
