"use client";

import type { NewsletterSubscriberOut } from "@approvalready/shared-types";
import { useState } from "react";

import { useAction } from "@/components/admin/useAction";
import { FormError } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";
import { formatDateTime } from "@/lib/labels";
import { SUBSCRIBER_STATUS_LABELS } from "@/lib/marketing";

/** Staff: the guides email list, searchable by email (posted, so addresses never end up in
 * the page address), with a way to take someone off it. */
export function SubscriberList({ initial }: { initial: NewsletterSubscriberOut[] }) {
  const { busy, error, run } = useAction();
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState(initial);

  async function search() {
    const found = await run(() =>
      apiRequest<NewsletterSubscriberOut[]>("POST", "/admin/marketing/subscribers/search", {
        query,
      }),
    );
    if (found) setRows(found);
  }

  async function remove(id: string) {
    if (!window.confirm("Take this person off the email list?")) return;
    const done = await run(() =>
      apiRequest<NewsletterSubscriberOut>("POST", `/admin/marketing/subscribers/${id}/unsubscribe`),
    );
    if (done) setRows((all) => all.map((r) => (r.id === id ? done : r)));
  }

  return (
    <>
      <form
        method="post"
        className="form"
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          void search();
        }}
      >
        <label>
          Search by email
          <input
            type="search"
            name="query"
            autoComplete="off"
            maxLength={320}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <button type="submit" className="button button-secondary" disabled={busy}>
          Search
        </button>
      </form>
      <FormError message={error} />
      {rows.length === 0 ? (
        <p className="muted">Nobody found.</p>
      ) : (
        <div className="table-scroll">
          <table className="usage-table" aria-label="Email list">
            <thead>
              <tr>
                <th>Email</th>
                <th>Status</th>
                <th>Joined from</th>
                <th>Since</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>{r.email}</td>
                  <td>{SUBSCRIBER_STATUS_LABELS[r.status]}</td>
                  <td>{r.source === "ACCOUNT" ? "Their account" : "Sign-up form"}</td>
                  <td>
                    {formatDateTime(
                      (r.status === "UNSUBSCRIBED" ? r.unsubscribed_at : r.subscribed_at) ??
                        r.created_at,
                    )}
                  </td>
                  <td>
                    {r.status === "SUBSCRIBED" ? (
                      <button
                        type="button"
                        className="button button-secondary"
                        disabled={busy}
                        onClick={() => void remove(r.id)}
                      >
                        Unsubscribe
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
