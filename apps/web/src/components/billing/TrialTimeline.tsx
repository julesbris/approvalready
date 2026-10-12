import type { PlusOfferOut } from "@approvalready/shared-types";

import { trialTimeline } from "@/lib/membership";

/** What happens and what is charged, from today to the first charge, as one card. */
export function TrialTimeline({
  offer,
  trial,
  title,
}: {
  offer: PlusOfferOut;
  trial: boolean;
  title: string;
}) {
  return (
    <aside className="example-card plus-timeline" aria-label={title}>
      <p className="example-ref">{offer.product_name}</p>
      <p className="example-title">{title}</p>
      <ol className="example-rows">
        {trialTimeline(offer, trial).map((row) => (
          <li key={row.when}>
            <span>
              <strong>{row.when}</strong>
              <br />
              <span className="muted">{row.what}</span>
            </span>
            <span className="plus-amount">{row.amount}</span>
          </li>
        ))}
      </ol>
      <p className="example-foot">Prices include GST. Cancel any time in Billing.</p>
    </aside>
  );
}
