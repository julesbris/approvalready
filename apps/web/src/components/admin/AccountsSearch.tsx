"use client";

import type { AccountSummary } from "@approvalready/shared-types";
import Link from "next/link";
import { useState } from "react";

import { useAction } from "@/components/admin/useAction";
import { FormError } from "@/components/auth/FormStatus";
import { ACCOUNT_FILTERS, accountState } from "@/lib/accounts";
import { apiRequest } from "@/lib/client-api";
import { formatDateTime, ROLE_LABELS } from "@/lib/labels";

/** Staff: find an account by email, name, business name or ABN. The search is posted, so
 * customers' email addresses never end up in the page address or server logs. */
export function AccountsSearch({ initial }: { initial: AccountSummary[] }) {
  const { busy, error, run } = useAction();
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [accounts, setAccounts] = useState(initial);
  const [searched, setSearched] = useState(false);

  async function search() {
    const found = await run(() =>
      apiRequest<AccountSummary[]>("POST", "/admin/accounts/search", {
        query,
        status: status || null,
      }),
    );
    if (found) {
      setAccounts(found);
      setSearched(true);
    }
  }

  return (
    <>
      <form
        method="post"
        className="form form-wide"
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          void search();
        }}
      >
        <div className="field-row">
          <label>
            Email, name, business name or ABN
            <input
              name="query"
              type="search"
              maxLength={200}
              autoComplete="off"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          <label>
            Show
            <select name="status" value={status} onChange={(e) => setStatus(e.target.value)}>
              {ACCOUNT_FILTERS.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <FormError message={error} />
        <div className="button-row tight">
          <button type="submit" className="button" disabled={busy}>
            {busy ? "Searching…" : "Search"}
          </button>
        </div>
      </form>
      <h2 className="section-title">
        {searched
          ? `Found ${accounts.length === 50 ? "50 or more" : accounts.length}`
          : "Newest accounts"}
      </h2>
      {accounts.length === 0 ? (
        <p className="muted">No accounts match.</p>
      ) : (
        <ul className="card-list" aria-label="Accounts">
          {accounts.map((a) => (
            <li key={a.id} className="card">
              <Link className="card-title" href={`/admin/accounts/${a.id}`}>
                {a.display_name}
              </Link>
              <div className="muted">
                {a.email} · joined {formatDateTime(a.created_at)}
                {a.last_login_at ? ` · last signed in ${formatDateTime(a.last_login_at)}` : ""}
                {a.organisations > 1 ? ` · ${a.organisations} organisations` : ""}
                {a.platform_role ? ` · ${ROLE_LABELS[a.platform_role] ?? a.platform_role}` : ""}
              </div>
              <span className="status">{accountState(a)}</span>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
