"use client";

import type { FeeOut, LeadMatchStatus, LeadOfferOut } from "@approvalready/shared-types";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useAction } from "@/components/admin/useAction";
import { FormError } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";
import { MATCH_STATUS_LABELS, NEXT_OUTCOMES, money } from "@/lib/leads";

/** Accept or decline an offered referral. */
export function OfferActions({
  organisationId,
  matchId,
  fee,
  canClaim,
}: {
  organisationId: string;
  matchId: string;
  fee: FeeOut | null;
  canClaim: boolean;
}) {
  const router = useRouter();
  const { busy, error, run } = useAction();
  const [reason, setReason] = useState("");
  const base = `/organisations/${organisationId}/partner/leads/${matchId}`;

  async function claim() {
    const done = await run(() => apiRequest<LeadOfferOut>("POST", `${base}/claim`));
    if (done !== null) router.refresh();
  }
  async function decline() {
    const done = await run(() =>
      apiRequest<LeadOfferOut>("POST", `${base}/decline`, { reason: reason.trim() || null }),
    );
    if (done !== null) router.refresh();
  }

  if (!canClaim) {
    return <p className="muted">Ask an administrator of your account to accept referrals.</p>;
  }
  return (
    <section className="panel" aria-labelledby="accept-title">
      <h2 id="accept-title" className="section-title">
        Accept this referral?
      </h2>
      {fee ? (
        <p>
          {fee.fee_cents > 0 ? <strong>{money(fee.fee_cents)}. </strong> : null}
          {fee.explanation}
          {fee.fee_cents > 0 ? ` Your credit: ${money(fee.balance_cents)}.` : ""}
        </p>
      ) : null}
      <p className="muted">
        Accepting gives you the contact details the customer chose to share. Only accept work you
        can take on.
      </p>
      <FormError message={error} />
      <div className="button-row">
        <button
          type="button"
          className="button"
          disabled={busy || (fee !== null && !fee.can_afford)}
          onClick={() => void claim()}
        >
          Accept{fee && fee.fee_cents > 0 ? ` for ${money(fee.fee_cents)}` : ""}
        </button>
      </div>
      <label>
        Not for you? Tell us why (optional)
        <input value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />
      </label>
      <div className="button-row">
        <button
          type="button"
          className="button-secondary"
          disabled={busy}
          onClick={() => void decline()}
        >
          Decline
        </button>
      </div>
    </section>
  );
}

/** Record what happened after accepting: contacted, quoted, won or lost. */
export function OutcomeActions({
  organisationId,
  matchId,
  status,
  canClaim,
}: {
  organisationId: string;
  matchId: string;
  status: LeadMatchStatus;
  canClaim: boolean;
}) {
  const router = useRouter();
  const { busy, error, run } = useAction();
  const [note, setNote] = useState("");
  const next = NEXT_OUTCOMES[status] ?? [];
  if (!canClaim || next.length === 0) return null;

  async function record(to: LeadMatchStatus) {
    const done = await run(() =>
      apiRequest<LeadOfferOut>(
        "POST",
        `/organisations/${organisationId}/partner/leads/${matchId}/outcome`,
        { status: to, note: note.trim() || null },
      ),
    );
    if (done !== null) {
      setNote("");
      router.refresh();
    }
  }
  return (
    <section className="panel" aria-labelledby="outcome-title">
      <h2 id="outcome-title" className="section-title">
        What happened?
      </h2>
      <label>
        Note (optional)
        <input value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
      </label>
      <FormError message={error} />
      <div className="button-row">
        {next.map((to) => (
          <button
            key={to}
            type="button"
            className={to === "WON" ? "button" : "button-secondary"}
            disabled={busy}
            onClick={() => void record(to)}
          >
            {MATCH_STATUS_LABELS[to]}
          </button>
        ))}
      </div>
    </section>
  );
}
