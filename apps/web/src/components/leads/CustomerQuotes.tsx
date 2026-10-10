"use client";

import type { CustomerQuoteOut } from "@approvalready/shared-types";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useAction } from "@/components/admin/useAction";
import { FormError } from "@/components/auth/FormStatus";
import { QuoteDetails } from "@/components/leads/QuoteActions";
import { apiRequest } from "@/lib/client-api";
import { formatDateTime } from "@/lib/labels";
import { money } from "@/lib/leads";
import { formatDate } from "@/lib/questionnaire";
import { groupByJob, quoteStatusClass, quoteStatusLabel } from "@/lib/quotes";

/** The customer's quotes, one comparison per job: prices side by side, then each quote with
 * accept and decline. */
export function CustomerQuotes({
  organisationId,
  projectId,
  quotes,
  canWrite,
}: {
  organisationId: string;
  projectId: string;
  quotes: CustomerQuoteOut[];
  canWrite: boolean;
}) {
  const router = useRouter();
  const { busy, error, run } = useAction();
  const [notes, setNotes] = useState<Record<string, string>>({});
  const base = `/organisations/${organisationId}/projects/${projectId}/quotes`;

  async function accept(quote: CustomerQuoteOut, others: number) {
    const confirmed = window.confirm(
      `Accept ${quote.partner.name}'s quote for ${money(quote.total_inc_gst_cents)}? We'll let ` +
        "them know you want to go ahead. Your agreement for the work is with them.",
    );
    if (!confirmed) return;
    const declineOthers =
      others > 0 &&
      window.confirm(
        `Also decline the other ${others === 1 ? "quote" : `${others} quotes`} for this job? ` +
          "We'll tell those partners you chose someone else.",
      );
    const note = notes[quote.id]?.trim() || null;
    const done = await run(() =>
      apiRequest<CustomerQuoteOut[]>("POST", `${base}/${quote.id}/accept`, {
        decline_others: declineOthers,
        note,
      }),
    );
    if (done !== null) router.refresh();
  }

  async function decline(quote: CustomerQuoteOut) {
    if (!window.confirm(`Decline ${quote.partner.name}'s quote? They may send a revised one.`))
      return;
    const note = notes[quote.id]?.trim() || null;
    const done = await run(() =>
      apiRequest<CustomerQuoteOut[]>("POST", `${base}/${quote.id}/decline`, { note }),
    );
    if (done !== null) router.refresh();
  }

  if (quotes.length === 0) {
    return (
      <p className="muted">
        No quotes yet. Partners who accept your request can send you one here.
      </p>
    );
  }
  return (
    <>
      <FormError message={error} />
      {groupByJob(quotes).map((group) => {
        const job = group[0]!;
        const waiting = group.filter((q) => q.status === "SENT" && !q.expired);
        return (
          <section key={job.lead_id} aria-label={`Quotes: ${job.category_label}`}>
            <h3 className="card-title">{job.category_label}</h3>
            <div className="table-scroll">
              <table className="usage-table">
                <thead>
                  <tr>
                    <th scope="col">Partner</th>
                    <th scope="col">Total with any GST</th>
                    <th scope="col">Valid until</th>
                    <th scope="col">Could start</th>
                    <th scope="col">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {group.map((q) => (
                    <tr key={q.id}>
                      <td>
                        <a href={`#quote-${q.id}`}>{q.partner.name}</a>
                      </td>
                      <td className="amount">{money(q.total_inc_gst_cents)}</td>
                      <td>{formatDate(q.valid_until)}</td>
                      <td>{q.start_estimate ?? "Not given"}</td>
                      <td>
                        <span className={quoteStatusClass(q)}>{quoteStatusLabel(q)}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <ul className="finding-list">
              {group.map((q) => {
                const others = waiting.filter((o) => o.id !== q.id).length;
                const answerable = canWrite && q.status === "SENT";
                return (
                  <li key={q.id} id={`quote-${q.id}`} className="card">
                    <p className="card-title">
                      {q.partner.name}: {q.title}{" "}
                      <span className={quoteStatusClass(q)}>{quoteStatusLabel(q)}</span>
                    </p>
                    <p className="muted">
                      {q.version > 1 ? `Revised (version ${q.version}), sent ` : "Sent "}
                      {formatDateTime(q.sent_at)}.{" "}
                      {[q.partner.phone, q.partner.contact_email, q.partner.website]
                        .filter(Boolean)
                        .join(" · ")}
                    </p>
                    <QuoteDetails quote={q} />
                    {q.response_note && q.status !== "SENT" ? (
                      <p className="muted">Note: &ldquo;{q.response_note}&rdquo;</p>
                    ) : null}
                    {answerable ? (
                      <>
                        <label>
                          A note for {q.partner.name} (optional)
                          <input
                            value={notes[q.id] ?? ""}
                            maxLength={500}
                            onChange={(e) =>
                              setNotes((all) => ({ ...all, [q.id]: e.target.value }))
                            }
                          />
                        </label>
                        <div className="button-row">
                          {!q.expired ? (
                            <button
                              type="button"
                              className="button"
                              disabled={busy}
                              onClick={() => void accept(q, others)}
                            >
                              Accept quote
                            </button>
                          ) : null}
                          <button
                            type="button"
                            className="button-secondary"
                            disabled={busy}
                            onClick={() => void decline(q)}
                          >
                            Decline
                          </button>
                        </div>
                        {q.expired ? (
                          <p className="muted">
                            This quote&apos;s date has passed. Ask {q.partner.name} for a new one.
                          </p>
                        ) : null}
                      </>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}
      <p className="muted">
        Accepting a quote tells the partner you want to go ahead. The agreement for the work, and
        any payment, is between you and them: ApprovalReady isn&apos;t part of it. Check licences,
        insurance and the terms before you sign anything.
      </p>
    </>
  );
}
