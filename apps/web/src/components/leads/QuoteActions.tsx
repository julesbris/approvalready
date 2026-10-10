"use client";

import type { GstTreatment, LeadOfferOut, QuoteIn, QuoteOut } from "@approvalready/shared-types";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { useAction } from "@/components/admin/useAction";
import { FormError } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";
import { formatDateTime } from "@/lib/labels";
import { money } from "@/lib/leads";
import { formatDate } from "@/lib/questionnaire";
import {
  GST_LABELS,
  gstAmounts,
  isoDateAfter,
  parseAmount,
  quoteStatusClass,
  quoteStatusLabel,
} from "@/lib/quotes";

type Line = { description: string; amount: string };

const MAX_LINES = 20;

/** Send the customer a written quote (or a revision of the one waiting). */
export function QuoteForm({
  organisationId,
  matchId,
  revising,
}: {
  organisationId: string;
  matchId: string;
  revising: QuoteOut | null;
}) {
  const router = useRouter();
  const { busy, error, run, setError } = useAction();
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState(revising?.title ?? "");
  const [scope, setScope] = useState(revising?.scope ?? "");
  const [lines, setLines] = useState<Line[]>(
    revising
      ? revising.line_items.map((l) => ({
          description: l.description,
          amount: (l.amount_cents / 100).toFixed(2),
        }))
      : [{ description: "", amount: "" }],
  );
  const [gst, setGst] = useState<GstTreatment>(revising?.gst ?? "INCLUDED");
  const [validUntil, setValidUntil] = useState(isoDateAfter(30));
  const [start, setStart] = useState(revising?.start_estimate ?? "");
  const [terms, setTerms] = useState(revising?.terms ?? "");

  const amounts = lines.map((l) => parseAmount(l.amount));
  const subtotal = amounts.reduce<number>((sum, a) => sum + (a ?? 0), 0);
  const totals = gstAmounts(subtotal, gst);

  function setLine(i: number, patch: Partial<Line>) {
    setLines((all) => all.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (amounts.some((a) => a === null)) {
      setError("Enter each amount in dollars, for example 1800 or 1,800.50.");
      return;
    }
    const body: QuoteIn = {
      title: title.trim(),
      scope: scope.trim(),
      line_items: lines.map((l, i) => ({
        description: l.description.trim(),
        amount_cents: amounts[i] ?? 0,
      })),
      gst,
      valid_until: validUntil,
      start_estimate: start.trim() || null,
      terms: terms.trim() || null,
    };
    const done = await run(() =>
      apiRequest<LeadOfferOut>(
        "POST",
        `/organisations/${organisationId}/partner/leads/${matchId}/quotes`,
        body,
      ),
    );
    if (done !== null) {
      setOpen(false);
      router.refresh();
    }
  }

  if (!open) {
    return (
      <div className="button-row">
        <button type="button" className="button" onClick={() => setOpen(true)}>
          {revising ? "Revise your quote" : "Send a quote"}
        </button>
      </div>
    );
  }
  return (
    <form method="post" className="form" onSubmit={(e) => void submit(e)}>
      <p className="muted">
        The customer sees this quote with your business name and contact details, and can accept or
        decline it here.
        {revising ? " Sending it replaces the quote they have now." : ""}
      </p>
      <label>
        Title
        <input
          value={title}
          minLength={3}
          maxLength={200}
          required
          placeholder="Development application for a secondary dwelling"
          onChange={(e) => setTitle(e.target.value)}
        />
      </label>
      <label>
        What the work includes (and doesn&apos;t)
        <textarea
          value={scope}
          minLength={10}
          maxLength={4000}
          rows={5}
          required
          onChange={(e) => setScope(e.target.value)}
        />
      </label>
      <fieldset className="plain-fieldset">
        <legend>Prices</legend>
        {lines.map((line, i) => (
          <div key={i} className="quote-line">
            <label>
              Item
              <input
                value={line.description}
                maxLength={200}
                required
                onChange={(e) => setLine(i, { description: e.target.value })}
              />
            </label>
            <label>
              Amount ($)
              <input
                value={line.amount}
                inputMode="decimal"
                required
                aria-invalid={amounts[i] === null && line.amount !== ""}
                onChange={(e) => setLine(i, { amount: e.target.value })}
              />
            </label>
            {lines.length > 1 ? (
              <button
                type="button"
                className="button-secondary"
                onClick={() => setLines((all) => all.filter((_, j) => j !== i))}
              >
                Remove
              </button>
            ) : null}
          </div>
        ))}
        {lines.length < MAX_LINES ? (
          <div className="button-row">
            <button
              type="button"
              className="button-secondary"
              onClick={() => setLines((all) => [...all, { description: "", amount: "" }])}
            >
              Add an item
            </button>
          </div>
        ) : null}
      </fieldset>
      <label>
        GST
        <select value={gst} onChange={(e) => setGst(e.target.value as GstTreatment)}>
          {Object.entries(GST_LABELS).map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <p>
        <strong>Total {money(totals.total)}</strong>
        {gst === "NOT_REGISTERED" ? " (no GST)" : ` (includes ${money(totals.gst)} GST)`}
      </p>
      <label>
        Valid until
        <input
          type="date"
          value={validUntil}
          min={isoDateAfter(0)}
          max={isoDateAfter(180)}
          required
          onChange={(e) => setValidUntil(e.target.value)}
        />
      </label>
      <label>
        When you could start (optional)
        <input value={start} maxLength={200} onChange={(e) => setStart(e.target.value)} />
      </label>
      <label>
        Deposit, payment and other terms (optional)
        <textarea
          value={terms}
          maxLength={2000}
          rows={3}
          onChange={(e) => setTerms(e.target.value)}
        />
      </label>
      <FormError message={error} />
      <div className="button-row">
        <button type="submit" className="button" disabled={busy}>
          Send quote
        </button>
        <button type="button" className="button-secondary" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
    </form>
  );
}

/** One quote's content: the prices, GST, dates and terms. */
export function QuoteDetails({ quote }: { quote: QuoteOut }) {
  return (
    <>
      <p className="quote-scope">{quote.scope}</p>
      <table className="usage-table">
        <tbody>
          {quote.line_items.map((l, i) => (
            <tr key={i}>
              <td>{l.description}</td>
              <td className="amount">{money(l.amount_cents)}</td>
            </tr>
          ))}
          <tr>
            <th scope="row">
              Total{quote.gst === "NOT_REGISTERED" ? " (no GST)" : " including GST"}
            </th>
            <td className="amount">
              <strong>{money(quote.total_inc_gst_cents)}</strong>
            </td>
          </tr>
        </tbody>
      </table>
      <p className="muted">
        {GST_LABELS[quote.gst]}
        {quote.gst_cents > 0 ? ` (GST ${money(quote.gst_cents)})` : ""}. Valid until{" "}
        {formatDate(quote.valid_until)}.
        {quote.start_estimate ? ` Could start: ${quote.start_estimate}.` : ""}
      </p>
      {quote.terms ? <p className="quote-scope">Terms: {quote.terms}</p> : null}
    </>
  );
}

/** The quotes a partner sent for a referral, newest first, and withdrawing one. */
export function PartnerQuotes({
  organisationId,
  matchId,
  quotes,
  canClaim,
}: {
  organisationId: string;
  matchId: string;
  quotes: QuoteOut[];
  canClaim: boolean;
}) {
  const router = useRouter();
  const { busy, error, run } = useAction();

  async function withdraw(id: string) {
    if (!window.confirm("Withdraw this quote? The customer will no longer be able to accept it."))
      return;
    const done = await run(() =>
      apiRequest<LeadOfferOut>(
        "POST",
        `/organisations/${organisationId}/partner/leads/${matchId}/quotes/${id}/withdraw`,
      ),
    );
    if (done !== null) router.refresh();
  }

  if (quotes.length === 0) return null;
  const [current, ...earlier] = quotes;
  return (
    <>
      <FormError message={error} />
      {current ? (
        <div className="card">
          <p className="card-title">
            {current.title}{" "}
            <span className={quoteStatusClass(current)}>{quoteStatusLabel(current)}</span>
          </p>
          <p className="muted">
            Version {current.version}, sent {formatDateTime(current.sent_at)}.
            {current.response_note ? ` Customer's note: “${current.response_note}”` : ""}
          </p>
          <QuoteDetails quote={current} />
          {canClaim && current.status === "SENT" ? (
            <div className="button-row">
              <button
                type="button"
                className="button-secondary"
                disabled={busy}
                onClick={() => void withdraw(current.id)}
              >
                Withdraw quote
              </button>
            </div>
          ) : null}
        </div>
      ) : null}
      {earlier.length > 0 ? (
        <details>
          <summary>Earlier versions ({earlier.length})</summary>
          <ul>
            {earlier.map((q) => (
              <li key={q.id}>
                Version {q.version}: {money(q.total_inc_gst_cents)}, {quoteStatusLabel(q)}
                {q.response_note ? ` (“${q.response_note}”)` : ""}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </>
  );
}
