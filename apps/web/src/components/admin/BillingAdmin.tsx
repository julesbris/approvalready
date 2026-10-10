"use client";

import type {
  BillingStatusOut,
  PriceInterval,
  ProductOut,
  StripeEventOut,
} from "@approvalready/shared-types";
import { type FormEvent, useState } from "react";

import { useAction } from "@/components/admin/useAction";
import { FormError } from "@/components/auth/FormStatus";
import { limitLabel, parseDollars, priceLabel } from "@/lib/billing";
import { apiRequest } from "@/lib/client-api";
import { formatDateTime } from "@/lib/labels";

type Props = { status: BillingStatusOut; products: ProductOut[]; events: StripeEventOut[] };

const RECURRING = new Set(["SAAS", "PARTNER_PLAN"]);

function PriceForm({
  product,
  disabled,
  onSaved,
}: {
  product: ProductOut;
  disabled: boolean;
  onSaved: (p: ProductOut) => void;
}) {
  const recurring = RECURRING.has(product.kind);
  const [dollars, setDollars] = useState("");
  const [interval, setChargeInterval] = useState<PriceInterval>(recurring ? "MONTH" : "ONE_TIME");
  const { busy, error, run, setError } = useAction();

  async function submit(event: FormEvent) {
    event.preventDefault();
    const cents = parseDollars(dollars);
    if (cents === null) {
      setError("Enter an amount in dollars, like 249 or 249.50.");
      return;
    }
    const current = product.prices.find((p) => p.active && p.interval === interval);
    if (current && !window.confirm(`Replace ${priceLabel(current)} with the new price?`)) return;
    const data = await run(() =>
      apiRequest<ProductOut>("POST", `/admin/billing/products/${product.id}/prices`, {
        amount_cents: cents,
        interval,
      }),
    );
    if (data) {
      setDollars("");
      onSaved(data);
    }
  }

  return (
    <form method="post" className="form" onSubmit={(e) => void submit(e)}>
      <div className="button-row">
        <label>
          New price in dollars, including GST
          <input
            inputMode="decimal"
            value={dollars}
            onChange={(e) => setDollars(e.target.value)}
            placeholder="249.00"
            required
          />
        </label>
        {recurring ? (
          <label>
            Charged
            <select
              value={interval}
              onChange={(e) => setChargeInterval(e.target.value as PriceInterval)}
            >
              <option value="MONTH">Monthly</option>
              <option value="YEAR">Yearly</option>
            </select>
          </label>
        ) : null}
        <button type="submit" className="button-secondary" disabled={busy || disabled}>
          Set price
        </button>
      </div>
      <FormError message={error} />
    </form>
  );
}

/** Staff: prices for each catalogue product, and the Stripe webhook log. */
export function BillingAdmin({ status, products: initial, events: initialEvents }: Props) {
  const [products, setProducts] = useState(initial);
  const [events, setEvents] = useState(initialEvents);
  const { busy, error, run } = useAction();

  const replace = (p: ProductOut) =>
    setProducts((all) => all.map((x) => (x.id === p.id ? p : x)));

  return (
    <>
      <section className="panel" aria-labelledby="stripe-title">
        <h2 id="stripe-title" className="section-title">
          Stripe
        </h2>
        {status.enabled ? (
          <p>
            Switched on{status.test_mode ? " in test mode (no real money moves)" : ", live"}.
          </p>
        ) : (
          <p className="notice">
            Switched off (PAYMENTS_PROVIDER=none). Customers can&apos;t buy anything and plan
            limits don&apos;t apply. Prices can only be set once payments are on.
          </p>
        )}
        <p className="muted">
          Webhook address: <code>https://api.&lt;your domain&gt;{status.webhook_path}</code>.
          Events to send: {status.webhook_events.join(", ")}.
        </p>
      </section>

      <FormError message={error} />
      {products.map((product) => {
        const onSale = product.prices.filter((p) => p.active);
        const past = product.prices.filter((p) => !p.active);
        return (
          <section key={product.id} className="panel" aria-labelledby={`product-${product.id}`}>
            <h2 id={`product-${product.id}`} className="section-title">
              {product.name}
              {product.active ? "" : " (no longer in the catalogue)"}
            </h2>
            <p className="muted">
              {product.key} · {product.description}
            </p>
            {product.features.map((f) => (
              <p key={f.key} className="muted">
                {f.description}: {limitLabel(f.limit)}
              </p>
            ))}
            {onSale.length === 0 ? <p>Not on sale.</p> : null}
            <ul className="task-list" aria-label={`${product.name} prices`}>
              {onSale.map((price) => (
                <li key={price.id} className="task">
                  <span>
                    <strong>{priceLabel(price)}</strong> since {formatDateTime(price.created_at)}
                  </span>
                  <button
                    type="button"
                    className="button-link"
                    disabled={busy}
                    onClick={async () => {
                      if (!window.confirm(`Take ${priceLabel(price)} off sale?`)) return;
                      const data = await run(() =>
                        apiRequest<ProductOut>(
                          "POST",
                          `/admin/billing/prices/${price.id}/deactivate`,
                        ),
                      );
                      if (data) replace(data);
                    }}
                  >
                    Take off sale
                  </button>
                </li>
              ))}
            </ul>
            {product.active ? (
              <PriceForm product={product} disabled={!status.enabled} onSaved={replace} />
            ) : null}
            {past.length > 0 ? (
              <details>
                <summary>Past prices ({past.length})</summary>
                <ul className="task-list">
                  {past.map((price) => (
                    <li key={price.id} className="task">
                      <span>{priceLabel(price)}</span>
                      <span className="muted">
                        {formatDateTime(price.created_at)} to{" "}
                        {price.deactivated_at ? formatDateTime(price.deactivated_at) : "?"}
                      </span>
                    </li>
                  ))}
                </ul>
              </details>
            ) : null}
          </section>
        );
      })}

      <section className="panel" aria-labelledby="events-title">
        <h2 id="events-title" className="section-title">
          Recent Stripe events
        </h2>
        {events.length === 0 ? <p className="muted">None received yet.</p> : null}
        <table className="usage-table">
          <thead>
            <tr>
              <th>Received</th>
              <th>Event</th>
              <th>Outcome</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {events.map((e) => (
              <tr key={e.id}>
                <td>{formatDateTime(e.received_at)}</td>
                <td>
                  {e.type}
                  {e.livemode ? "" : " (test)"}
                </td>
                <td>
                  {e.status}
                  {e.error ? `: ${e.error}` : ""}
                </td>
                <td>
                  {e.status === "FAILED" ? (
                    <button
                      type="button"
                      className="button-link"
                      disabled={busy}
                      onClick={async () => {
                        const data = await run(() =>
                          apiRequest<StripeEventOut>(
                            "POST",
                            `/admin/billing/events/${e.id}/retry`,
                          ),
                        );
                        if (data) setEvents((all) => all.map((x) => (x.id === data.id ? data : x)));
                      }}
                    >
                      Retry
                    </button>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}
