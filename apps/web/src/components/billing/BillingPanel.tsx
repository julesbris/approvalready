"use client";

import type { BillingOut, ProductOut, RedirectOut } from "@approvalready/shared-types";

import { useAction } from "@/components/admin/useAction";
import { FormError } from "@/components/auth/FormStatus";
import {
  INVOICE_STATUS_LABELS,
  PAYMENT_STATUS_LABELS,
  SUBSCRIPTION_STATUS_LABELS,
  formatMoney,
  limitLabel,
  priceLabel,
} from "@/lib/billing";
import { type ApiResult, apiRequest } from "@/lib/client-api";
import { formatDateTime } from "@/lib/labels";

type Props = {
  organisationId: string;
  billing: BillingOut;
  /** Back from Stripe Checkout: "done" or "cancelled". */
  checkout: string | null;
};

const LIVE = new Set(["INCOMPLETE", "TRIALING", "ACTIVE", "PAST_DUE", "UNPAID", "PAUSED"]);

function PlanCard({
  plan,
  busy,
  onChoose,
}: {
  plan: ProductOut;
  busy: boolean;
  onChoose: (priceId: string) => void;
}) {
  return (
    <li className="task">
      <span>
        <strong>{plan.name}</strong>
        <br />
        {plan.description}
        {plan.features.map((f) => (
          <span key={f.key} className="muted">
            <br />
            {f.description}: {limitLabel(f.limit)}
          </span>
        ))}
      </span>
      <span className="button-row">
        {plan.prices.map((price) => (
          <button
            key={price.id}
            type="button"
            className="button"
            disabled={busy}
            onClick={() => onChoose(price.id)}
          >
            {priceLabel(price)}
          </button>
        ))}
      </span>
    </li>
  );
}

/** An organisation's plan, usage, payments and invoices, with Stripe checkout and portal. */
export function BillingPanel({ organisationId, billing, checkout }: Props) {
  const { busy, error, run } = useAction();
  const base = `/organisations/${organisationId}/billing`;
  const live = billing.subscriptions.filter((s) => LIVE.has(s.status));
  const past = billing.subscriptions.filter((s) => !LIVE.has(s.status));

  async function go(call: () => Promise<ApiResult<RedirectOut>>) {
    const data = await run(call);
    if (data) window.location.assign(data.url);
  }

  return (
    <>
      {!billing.enabled ? (
        <p className="notice">Payments aren&apos;t switched on yet, so nothing here costs money.</p>
      ) : null}
      {billing.enabled && billing.test_mode ? (
        <p className="notice">Test mode: payments use Stripe test cards and no money moves.</p>
      ) : null}
      {checkout === "done" ? (
        <p className="notice">
          Thanks. We&apos;re confirming your payment with Stripe; reload this page in a moment
          to see your plan.
        </p>
      ) : null}
      {checkout === "cancelled" ? (
        <p className="notice">The payment wasn&apos;t completed. Nothing was charged.</p>
      ) : null}
      <FormError message={error} />

      <section className="panel" aria-labelledby="plan-title">
        <h2 id="plan-title" className="section-title">
          Your plan
        </h2>
        {live.length === 0 ? <p>Free. You haven&apos;t chosen a paid plan.</p> : null}
        <ul className="task-list" aria-label="Current plan">
          {live.map((s) => (
            <li key={s.id} className="task">
              <span>
                <strong>{s.product_name}</strong>{" "}
                <span className={`status status-${s.status.toLowerCase()}`}>
                  {SUBSCRIPTION_STATUS_LABELS[s.status]}
                </span>
                <br />
                {priceLabel(s)}
                {s.current_period_end
                  ? s.cancel_at_period_end
                    ? `. Ends ${formatDateTime(s.current_period_end)}.`
                    : `. Renews ${formatDateTime(s.current_period_end)}.`
                  : ""}
                {s.status === "PAST_DUE" ? (
                  <span className="muted">
                    <br />
                    {s.gives_plan
                      ? "The last payment failed. Update your card to keep your plan."
                      : "The last payment failed and the grace period has ended. Update your card to restore your plan."}
                  </span>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
        {billing.enabled && billing.has_billing_account ? (
          <div className="button-row">
            <button
              type="button"
              className="button-secondary"
              disabled={busy}
              onClick={() => void go(() => apiRequest<RedirectOut>("POST", `${base}/portal`))}
            >
              Manage billing
            </button>
          </div>
        ) : null}
        {billing.enabled && billing.has_billing_account ? (
          <p className="muted">
            Change your card, download invoices or cancel your plan on Stripe&apos;s secure page.
          </p>
        ) : null}
      </section>

      {live.length === 0 && billing.plans.length > 0 ? (
        <section className="panel" aria-labelledby="plans-title">
          <h2 id="plans-title" className="section-title">
            Plans
          </h2>
          <p className="muted">Prices include GST. You pay on Stripe&apos;s secure checkout page.</p>
          <ul className="task-list" aria-label="Plans">
            {billing.plans.map((plan) => (
              <PlanCard
                key={plan.id}
                plan={plan}
                busy={busy}
                onChoose={(priceId) =>
                  void go(() =>
                    apiRequest<RedirectOut>("POST", `${base}/checkout`, { price_id: priceId }),
                  )
                }
              />
            ))}
          </ul>
        </section>
      ) : null}

      {billing.allowances.length > 0 ? (
        <section className="panel" aria-labelledby="usage-title">
          <h2 id="usage-title" className="section-title">
            Usage
          </h2>
          <ul className="task-list" aria-label="Usage">
            {billing.allowances.map((a) => (
              <li key={a.feature} className="task">
                <span>{a.description}</span>
                <span>
                  {a.in_use} of {limitLabel(a.enforced ? a.limit : null)}
                  {a.enforced && a.plan ? ` (${a.plan})` : ""}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="panel" aria-labelledby="payments-title">
        <h2 id="payments-title" className="section-title">
          Payments
        </h2>
        {billing.payments.length === 0 ? <p className="muted">No one-off payments yet.</p> : null}
        <ul className="task-list" aria-label="Payments">
          {billing.payments.map((p) => (
            <li key={p.id} className="task">
              <span>
                {p.product_name}: {formatMoney(p.amount_cents, p.currency)}
                {p.refunded_cents > 0
                  ? ` (${formatMoney(p.refunded_cents, p.currency)} refunded)`
                  : ""}
              </span>
              <span className="muted">
                {PAYMENT_STATUS_LABELS[p.status] ?? p.status} ·{" "}
                {formatDateTime(p.paid_at ?? p.created_at)}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <section className="panel" aria-labelledby="invoices-title">
        <h2 id="invoices-title" className="section-title">
          Invoices
        </h2>
        {billing.invoices.length === 0 ? <p className="muted">No invoices yet.</p> : null}
        <ul className="task-list" aria-label="Invoices">
          {billing.invoices.map((i) => (
            <li key={i.id} className="task">
              <span>
                {i.number ?? "Invoice"}: {formatMoney(i.amount_due_cents, i.currency)} ·{" "}
                {INVOICE_STATUS_LABELS[i.status] ?? i.status}
              </span>
              <span>
                {i.hosted_invoice_url ? (
                  <a href={i.hosted_invoice_url} target="_blank" rel="noopener noreferrer">
                    View
                  </a>
                ) : null}
                {i.invoice_pdf_url ? (
                  <>
                    {" · "}
                    <a href={i.invoice_pdf_url} target="_blank" rel="noopener noreferrer">
                      PDF
                    </a>
                  </>
                ) : null}{" "}
                <span className="muted">{formatDateTime(i.issued_at)}</span>
              </span>
            </li>
          ))}
        </ul>
      </section>

      {past.length > 0 ? (
        <section className="panel" aria-labelledby="past-title">
          <h2 id="past-title" className="section-title">
            Past plans
          </h2>
          <ul className="task-list" aria-label="Past plans">
            {past.map((s) => (
              <li key={s.id} className="task">
                <span>{s.product_name}</span>
                <span className="muted">
                  {SUBSCRIPTION_STATUS_LABELS[s.status]}
                  {s.canceled_at ? ` · ${formatDateTime(s.canceled_at)}` : ""}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </>
  );
}
