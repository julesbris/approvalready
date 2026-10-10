"use client";

import type {
  CreditKind,
  CreditStaffOut,
  LeadPriceOut,
  StaffLeadOut,
} from "@approvalready/shared-types";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useAction } from "@/components/admin/useAction";
import { FormError } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";
import { formatDateTime } from "@/lib/labels";
import {
  CREDIT_KIND_LABELS,
  LEAD_STATUS_LABELS,
  MATCH_STATUS_LABELS,
  leadPlace,
  money,
  parseDollars,
} from "@/lib/leads";

function PriceRow({ price }: { price: LeadPriceOut }) {
  const router = useRouter();
  const { busy, error, run, setError } = useAction();
  const [amount, setAmount] = useState(
    price.amount_cents ? (price.amount_cents / 100).toFixed(2) : "",
  );
  const url = `/admin/leads/prices/${encodeURIComponent(price.category_key)}`;

  async function save() {
    const cents = parseDollars(amount);
    if (cents === null) {
      setError("Enter a fee in dollars, like 25 or 25.50.");
      return;
    }
    const done = await run(() => apiRequest<LeadPriceOut>("PUT", url, { amount_cents: cents }));
    if (done !== null) router.refresh();
  }
  async function remove() {
    const done = await run(() => apiRequest<unknown>("DELETE", url));
    if (done !== null) {
      setAmount("");
      router.refresh();
    }
  }
  return (
    <tr>
      <td>{price.category_label}</td>
      <td>
        {price.restricted ? (
          <span className="muted">Never charged (restricted work)</span>
        ) : (
          <>
            <input
              aria-label={`Fee for ${price.category_label}`}
              value={amount}
              inputMode="decimal"
              maxLength={10}
              placeholder="No fee"
              onChange={(e) => setAmount(e.target.value)}
            />
            <FormError message={error} />
          </>
        )}
      </td>
      <td>{price.set_at ? formatDateTime(price.set_at) : ""}</td>
      <td>
        {price.restricted ? null : (
          <div className="button-row">
            <button
              type="button"
              className="button-secondary"
              disabled={busy}
              onClick={() => void save()}
            >
              Save
            </button>
            {price.price_id ? (
              <button
                type="button"
                className="button-secondary"
                disabled={busy}
                onClick={() => void remove()}
              >
                Remove
              </button>
            ) : null}
          </div>
        )}
      </td>
    </tr>
  );
}

/** Referral fees per category: charged only after a partner's included referrals. */
export function LeadPrices({ prices }: { prices: LeadPriceOut[] }) {
  return (
    <table className="table">
      <thead>
        <tr>
          <th>Category</th>
          <th>Fee per accepted referral (AUD)</th>
          <th>Set</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {prices.map((p) => (
          <PriceRow key={p.category_key} price={p} />
        ))}
      </tbody>
    </table>
  );
}

function RefundButton({ claimId }: { claimId: string }) {
  const router = useRouter();
  const { busy, error, run } = useAction();
  async function refund() {
    const note = window.prompt("Why is this fee being refunded? (at least 5 characters)");
    if (!note) return;
    const done = await run(() =>
      apiRequest<unknown>("POST", `/admin/leads/claims/${claimId}/refund`, { note }),
    );
    if (done !== null) router.refresh();
  }
  return (
    <>
      <button
        type="button"
        className="button-secondary"
        disabled={busy}
        onClick={() => void refund()}
      >
        Refund fee
      </button>
      <FormError message={error} />
    </>
  );
}

/** Recent referrals, who they were offered to, how each partner scored and what was paid. */
export function StaffLeads({ leads }: { leads: StaffLeadOut[] }) {
  if (leads.length === 0) return <p className="muted">No referrals yet.</p>;
  return (
    <ul className="finding-list">
      {leads.map((lead) => (
        <li key={lead.id} className="card">
          <p className="card-title">
            {lead.category_label}, {leadPlace(lead)}{" "}
            <span className={`status status-${lead.status.toLowerCase()}`}>
              {LEAD_STATUS_LABELS[lead.status]}
            </span>
          </p>
          <p className="muted">
            Made {formatDateTime(lead.created_at)}. {lead.claimed_count} of {lead.max_claims}{" "}
            accepted. Ends {formatDateTime(lead.expires_at)}.
          </p>
          {lead.matches.length > 0 ? (
            <table className="table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Partner</th>
                  <th>Score</th>
                  <th>Status</th>
                  <th>Fee</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {lead.matches.map((m) => (
                  <tr key={m.id}>
                    <td>{m.rank}</td>
                    <td>{m.partner_name}</td>
                    <td title={m.score_breakdown.map((f) => `${f.factor} ${f.points}/${f.max}`).join(", ")}>
                      {Math.round(m.score)}
                    </td>
                    <td>
                      {MATCH_STATUS_LABELS[m.status]}
                      {m.offered_at ? "" : <span className="muted"> (not offered yet)</span>}
                    </td>
                    <td>
                      {m.included
                        ? "Included"
                        : m.fee_cents
                          ? `${money(m.fee_cents)}${m.claim_refunded_at ? " refunded" : ""}`
                          : ""}
                    </td>
                    <td>
                      {m.claim_id && m.fee_cents && !m.claim_refunded_at ? (
                        <RefundButton claimId={m.claim_id} />
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="muted">No partner matched yet.</p>
          )}
        </li>
      ))}
    </ul>
  );
}

/** A partner's referral credit, with promotional credit and corrections by staff. */
export function PartnerCredits({ initial }: { initial: CreditStaffOut }) {
  const { busy, error, run } = useAction();
  const [credits, setCredits] = useState(initial);
  const [kind, setKind] = useState<CreditKind>("PROMO");
  const [amount, setAmount] = useState("");
  const [sign, setSign] = useState<1 | -1>(1);
  const [note, setNote] = useState("");

  async function adjust() {
    const cents = parseDollars(amount);
    if (cents === null) return;
    const done = await run(() =>
      apiRequest<CreditStaffOut>("POST", `/admin/leads/partners/${credits.partner_id}/credits`, {
        kind,
        delta_cents: kind === "PROMO" ? cents : sign * cents,
        note,
      }),
    );
    if (done !== null) {
      setCredits(done);
      setAmount("");
      setNote("");
    }
  }
  return (
    <section className="panel" aria-labelledby="credits-title">
      <h2 id="credits-title" className="section-title">
        Referral credit: {money(credits.balance_cents)}
      </h2>
      <div className="form">
        <label>
          Kind
          <select value={kind} onChange={(e) => setKind(e.target.value as CreditKind)}>
            <option value="PROMO">Credit from us</option>
            <option value="ADJUSTMENT">Correction</option>
          </select>
        </label>
        {kind === "ADJUSTMENT" ? (
          <label>
            Direction
            <select value={sign} onChange={(e) => setSign(Number(e.target.value) as 1 | -1)}>
              <option value={1}>Add credit</option>
              <option value={-1}>Take credit away</option>
            </select>
          </label>
        ) : null}
        <label>
          Amount (AUD)
          <input
            value={amount}
            inputMode="decimal"
            maxLength={10}
            onChange={(e) => setAmount(e.target.value)}
          />
        </label>
        <label>
          Reason (the partner sees this)
          <input value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} />
        </label>
        <FormError message={error} />
        <div className="button-row">
          <button
            type="button"
            className="button-secondary"
            disabled={busy || parseDollars(amount) === null || note.trim().length < 5}
            onClick={() => void adjust()}
          >
            Record
          </button>
        </div>
      </div>
      {credits.entries.length > 0 ? (
        <table className="table">
          <thead>
            <tr>
              <th>When</th>
              <th>What</th>
              <th>Amount</th>
              <th>After</th>
            </tr>
          </thead>
          <tbody>
            {credits.entries.map((e) => (
              <tr key={e.id}>
                <td>{formatDateTime(e.created_at)}</td>
                <td>
                  {CREDIT_KIND_LABELS[e.kind]}
                  {e.note ? <span className="muted"> ({e.note})</span> : null}
                </td>
                <td>{money(e.delta_cents)}</td>
                <td>{money(e.balance_after_cents)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  );
}
