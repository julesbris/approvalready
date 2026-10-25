import type { Metadata } from "next";
import Link from "next/link";

import { FinanceCallout } from "@/components/finance/FinanceCallout";
import { PublicShell } from "@/components/public/PublicShell";
import { FINANCE_ENQUIRY_URL, FINANCE_SERVICES } from "@/lib/finance";

export const metadata: Metadata = {
  title: "Mortgages and finance",
  description:
    "Home loans, investment loans, construction and development finance, business loans and asset finance for vehicles, vessels and equipment. Make an enquiry with ApprovalReady.",
  alternates: { canonical: "/finance" },
};

export default function FinancePage() {
  return (
    <PublicShell>
      <article className="guide" aria-labelledby="finance-title">
        <p className="eyebrow">Mortgages and finance</p>
        <h1 id="finance-title" className="page-title">
          Finance for what you&apos;re getting approved
        </h1>
        <p className="lede">
          Once you know what you need approved, the next question is usually how to pay for it.
          Tell us what you&apos;re buying, building or starting and a finance specialist will
          contact you about the loan or asset finance that fits.
        </p>
        <p>
          <a
            className="button button-large"
            href={FINANCE_ENQUIRY_URL}
            rel="noopener noreferrer"
            target="_blank"
          >
            Make a finance enquiry
          </a>
        </p>

        <ul className="finance-services" aria-label="Finance we can help with">
          {FINANCE_SERVICES.map((service) => (
            <li key={service.title}>
              <h2>{service.title}</h2>
              <p className="muted">{service.text}</p>
              <ul>
                {service.points.map((point) => (
                  <li key={point}>{point}</li>
                ))}
              </ul>
            </li>
          ))}
        </ul>

        <section aria-labelledby="finance-how">
          <h2 id="finance-how" className="section-title">
            How it works
          </h2>
          <ol>
            <li>Send an enquiry with what you&apos;re buying, building or starting.</li>
            <li>A finance specialist contacts you to talk through your options.</li>
            <li>
              Keep your approvals moving in ApprovalReady while the finance is arranged:{" "}
              <Link href="/register">start a free check</Link>.
            </li>
          </ol>
        </section>

        <FinanceCallout showMore={false} />

        <p className="muted">
          ApprovalReady doesn&apos;t lend money or give credit or financial advice. Enquiries go
          to a finance specialist who will talk you through your options. Any loan is subject to
          the lender&apos;s approval, terms and fees.
        </p>
      </article>
    </PublicShell>
  );
}
