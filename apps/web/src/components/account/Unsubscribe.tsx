"use client";

import type { UnsubscribedOut, UnsubscribeOut } from "@approvalready/shared-types";
import Link from "next/link";
import { useEffect, useState } from "react";

import { FormError, FormNotice } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";
import { CATEGORY_LABELS } from "@/lib/notifications";

/**
 * The page an email's unsubscribe link opens. Needs a click, because link scanners open
 * links in emails; mail apps' own one-click unsubscribe posts to the API directly.
 */
export function Unsubscribe({ token }: { token: string }) {
  const query = `?token=${encodeURIComponent(token)}`;
  const [info, setInfo] = useState<UnsubscribeOut | null>(null);
  const [done, setDone] = useState<UnsubscribedOut["scope"] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void apiRequest<UnsubscribeOut>("GET", `/auth/unsubscribe${query}`).then((result) => {
      if (result.ok) setInfo(result.data);
      else setError(result.message);
    });
  }, [query]);

  async function stop(scope: UnsubscribedOut["scope"]) {
    setBusy(true);
    const result = await apiRequest<UnsubscribedOut>(
      "POST",
      `/auth/unsubscribe${query}&scope=${scope}`,
    );
    setBusy(false);
    if (result.ok) setDone(scope);
    else setError(result.message);
  }

  const settings = <Link href="/account#notifications">Choose which emails you get</Link>;
  const label = info ? CATEGORY_LABELS[info.category].title.toLowerCase() : "";
  if (done) {
    return (
      <FormNotice>
        {done === "all"
          ? "You won't get reminder or alert emails any more."
          : `You won't get ${label} emails any more.`}{" "}
        They still show in the app, and emails about your account are always sent. {settings}
      </FormNotice>
    );
  }
  if (!info) return <FormError message={error} />;
  return (
    <div className="form">
      {info.channel === "ALL" ? (
        <p>Stop getting {label} emails? You&apos;ll still see them in the app.</p>
      ) : (
        <p>You already don&apos;t get {label} emails.</p>
      )}
      <FormError message={error} />
      {info.channel === "ALL" ? (
        <button type="button" className="button" onClick={() => stop("category")} disabled={busy}>
          Stop {label} emails
        </button>
      ) : null}
      <button
        type="button"
        className="button button-secondary"
        onClick={() => stop("all")}
        disabled={busy}
      >
        Stop all reminder and alert emails
      </button>
      <p className="form-aside">{settings}</p>
    </div>
  );
}
