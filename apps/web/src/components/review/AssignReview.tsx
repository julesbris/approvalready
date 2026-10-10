"use client";

import type { StaffReviewOut } from "@approvalready/shared-types";
import { type FormEvent, useState } from "react";

import { useAction } from "@/components/admin/useAction";
import { FormError } from "@/components/auth/FormStatus";
import { formatMoney } from "@/lib/billing";
import { apiRequest } from "@/lib/client-api";
import { formatDateTime, verticalName } from "@/lib/labels";
import { formatDate } from "@/lib/questionnaire";
import {
  DISCIPLINE_LABELS,
  REFUND_REASON_LABELS,
  REVIEW_STATUS_LABELS,
  reviewerName,
} from "@/lib/review";

const REFUND_STATUS_LABELS: Record<string, string> = {
  PENDING: "Being sent to Stripe",
  SUBMITTED: "Accepted by Stripe, processing",
  SUCCEEDED: "Refunded",
  FAILED: "Failed",
};

/** Staff with billing.refund: give back part or all of what the customer paid. */
function RefundForm({
  view,
  onDone,
}: {
  view: StaffReviewOut;
  onDone: (updated: StaffReviewOut) => void;
}) {
  const payment = view.payment;
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const { busy, error, run } = useAction();
  if (!payment || payment.refundable_cents <= 0) return null;
  const { currency } = payment;
  const left = formatMoney(payment.refundable_cents, currency);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const cents = amount.trim() ? Math.round(Number(amount) * 100) : null;
    const what = cents ? formatMoney(cents, currency) : left;
    if (!window.confirm(`Refund ${what} to the customer? This can't be undone.`)) return;
    const updated = await run(() =>
      apiRequest<StaffReviewOut>("POST", `/admin/reviews/${view.review.id}/refund`, {
        amount_cents: cents,
        note: note.trim(),
      }),
    );
    if (updated) {
      setAmount("");
      setNote("");
      onDone(updated);
    }
  }

  return (
    <form method="post" className="form" onSubmit={(e) => void submit(e)}>
      <h3 className="finding-label">Refund</h3>
      <FormError message={error} />
      <label>
        Amount in dollars (leave empty to refund all {left})
        <input
          inputMode="decimal"
          value={amount}
          pattern="[0-9]+(\.[0-9]{1,2})?"
          onChange={(e) => setAmount(e.target.value)}
        />
      </label>
      <label>
        Why (kept for staff, not shown to the customer)
        <textarea
          value={note}
          required
          minLength={3}
          maxLength={500}
          rows={2}
          onChange={(e) => setNote(e.target.value)}
        />
      </label>
      <div className="button-row">
        <button type="submit" className="button" disabled={busy}>
          Refund
        </button>
      </div>
    </form>
  );
}

/** What the customer paid and what has been given back. */
function PaymentSummary({ view }: { view: StaffReviewOut }) {
  const payment = view.payment;
  if (!payment) return null;
  return (
    <div>
      <h3 className="finding-label">Payment</h3>
      <p>
        {formatMoney(payment.amount_cents, payment.currency)}
        {payment.paid_at ? `, paid ${formatDateTime(payment.paid_at)}` : ", not paid"}
        {payment.refunded_cents > 0
          ? `. Refunded so far: ${formatMoney(payment.refunded_cents, payment.currency)}.`
          : "."}
      </p>
      {payment.refunds.length > 0 ? (
        <ul className="task-list" aria-label="Refunds">
          {payment.refunds.map((r) => (
            <li key={r.id} className="task">
              <span>
                {formatMoney(r.amount_cents, r.currency)}: {REFUND_STATUS_LABELS[r.status]} (
                {REFUND_REASON_LABELS[r.reason]}, {formatDateTime(r.created_at)})
                {r.note ? <span className="muted"> · {r.note}</span> : null}
                {r.error ? <span className="form-error"> · Stripe said: {r.error}</span> : null}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** Staff: give a review request to an eligible professional, or take it back. */
export function AssignReview({
  initial,
  canRefund = false,
}: {
  initial: StaffReviewOut;
  canRefund?: boolean;
}) {
  const [view, setView] = useState(initial);
  const [professionalId, setProfessionalId] = useState(initial.candidates[0]?.id ?? "");
  const [due, setDue] = useState("");
  const { busy, error, run } = useAction();
  const review = view.review;
  const base = `/admin/reviews/${review.id}`;

  async function assign(event: FormEvent) {
    event.preventDefault();
    const updated = await run(() =>
      apiRequest<StaffReviewOut>("POST", `${base}/assign`, {
        professional_id: professionalId,
        due_on: due || null,
      }),
    );
    if (updated) setView(updated);
  }

  async function unassign() {
    const updated = await run(() => apiRequest<StaffReviewOut>("POST", `${base}/unassign`, {}));
    if (updated) setView(updated);
  }

  return (
    <section className="panel">
      <h1 className="page-title">
        {view.project_title} ({view.project_reference})
      </h1>
      <p>
        <span className="status">{REVIEW_STATUS_LABELS[review.status]}</span>{" "}
        {verticalName(view.vertical)} · requested {formatDate(review.created_at.slice(0, 10))}
      </p>
      {view.rule_sets_in_scope.length > 0 ? (
        <p className="muted">Assessed against: {view.rule_sets_in_scope.join(", ")}.</p>
      ) : null}
      {review.message ? <p className="notice">Customer&apos;s note: {review.message}</p> : null}
      {review.professional ? <p>Assigned to {reviewerName(review.professional)}.</p> : null}
      <FormError message={error} />
      {review.status === "REVIEW_REQUESTED" ? (
        view.candidates.length === 0 ? (
          <p>
            No active professional reviews {verticalName(view.vertical).toLowerCase()} projects
            yet.
          </p>
        ) : (
          <form method="post" className="form" onSubmit={assign}>
            <label>
              Professional
              <select value={professionalId} onChange={(e) => setProfessionalId(e.target.value)}>
                {view.candidates.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.display_name}, {DISCIPLINE_LABELS[c.discipline]} ({c.practice_name})
                  </option>
                ))}
              </select>
            </label>
            <label>
              Due by (optional)
              <input type="date" value={due} onChange={(e) => setDue(e.target.value)} />
            </label>
            <div className="button-row">
              <button type="submit" className="button" disabled={busy || !professionalId}>
                Assign
              </button>
            </div>
          </form>
        )
      ) : null}
      {review.status === "ASSIGNED" ? (
        <button type="button" className="button-link" disabled={busy} onClick={unassign}>
          Take it back (not started yet)
        </button>
      ) : null}
      <PaymentSummary view={view} />
      {canRefund ? <RefundForm view={view} onDone={setView} /> : null}
    </section>
  );
}
