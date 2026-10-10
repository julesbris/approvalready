"use client";

import type { LeadPreferencesOut, RedirectOut } from "@approvalready/shared-types";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useAction } from "@/components/admin/useAction";
import { FormError } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";
import { money } from "@/lib/leads";

/** Pause new referrals, or cap how many accepted referrals can be in progress. */
export function LeadPreferencesForm({
  organisationId,
  preferences,
}: {
  organisationId: string;
  preferences: LeadPreferencesOut;
}) {
  const router = useRouter();
  const { busy, error, run } = useAction();
  const [cap, setCap] = useState(preferences.max_open_leads?.toString() ?? "");
  const url = `/organisations/${organisationId}/partner/lead-preferences`;

  async function save(body: Record<string, unknown>) {
    const done = await run(() => apiRequest<LeadPreferencesOut>("PATCH", url, body));
    if (done !== null) router.refresh();
  }
  return (
    <div className="form">
      <p>
        {preferences.paused
          ? "New referrals are paused. Referrals you already accepted are not affected."
          : "You are receiving new referrals."}{" "}
        {preferences.in_progress} accepted referral{preferences.in_progress === 1 ? "" : "s"} in
        progress.
      </p>
      <div className="button-row">
        <button
          type="button"
          className="button-secondary"
          disabled={busy}
          onClick={() => void save({ paused: !preferences.paused })}
        >
          {preferences.paused ? "Start receiving referrals" : "Pause new referrals"}
        </button>
      </div>
      <div className="form inline-form">
        <label>
          Most referrals in progress at once (blank: no limit)
          <input
            value={cap}
            inputMode="numeric"
            maxLength={3}
            onChange={(e) => setCap(e.target.value)}
          />
        </label>
        <button
          type="button"
          className="button-secondary"
          disabled={busy}
          onClick={() =>
            void save(
              cap.trim() === ""
                ? { clear_max_open_leads: true }
                : { max_open_leads: Number(cap.trim()) },
            )
          }
        >
          Save limit
        </button>
      </div>
      <FormError message={error} />
    </div>
  );
}

/** Buy a credit pack through Stripe Checkout. */
export function BuyCreditsButton({
  organisationId,
  priceCents,
}: {
  organisationId: string;
  priceCents: number;
}) {
  const { busy, error, run } = useAction();
  async function buy() {
    const done = await run(() =>
      apiRequest<RedirectOut>("POST", `/organisations/${organisationId}/partner/credits/checkout`),
    );
    if (done !== null) window.location.assign(done.url);
  }
  return (
    <>
      <FormError message={error} />
      <div className="button-row">
        <button type="button" className="button" disabled={busy} onClick={() => void buy()}>
          Buy {money(priceCents)} of credit
        </button>
      </div>
    </>
  );
}
