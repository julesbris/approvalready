import Link from "next/link";

import { FINANCE_ENQUIRY_URL, financeOffer } from "@/lib/finance";

/**
 * A call to action for mortgages and finance, worded for the project area, that sends the
 * enquiry to our finance team. Shown wherever money for a purchase, build or asset comes up.
 */
export function FinanceCallout({
  vertical,
  showMore = true,
}: {
  vertical?: string | null;
  showMore?: boolean;
}) {
  const offer = financeOffer(vertical);
  const id = `finance-${(vertical ?? "all").toLowerCase()}`;
  return (
    <section className="finance-callout" aria-labelledby={id}>
      <div>
        <h2 id={id}>{offer.heading}</h2>
        <p>{offer.text}</p>
      </div>
      <p className="finance-actions">
        <a className="button" href={FINANCE_ENQUIRY_URL} rel="noopener noreferrer" target="_blank">
          Make a finance enquiry
        </a>
        {showMore ? <Link href="/finance">See all finance options</Link> : null}
      </p>
    </section>
  );
}
