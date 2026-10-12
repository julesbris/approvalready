import type { PlusOfferOut } from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";
import { connection } from "next/server";

import { TrialTimeline } from "@/components/billing/TrialTimeline";
import { SiteFooter } from "@/components/public/SiteFooter";
import { SiteHeader } from "@/components/public/SiteHeader";
import { PLUS_BENEFITS, plusPrice } from "@/lib/membership";
import { publicGet } from "@/lib/session";

export const metadata: Metadata = {
  title: "ApprovalReady Plus: your first month free",
  description:
    "Manage every approval project online: each step on a timeline with the forms, fees, contacts and checked local partners. First month free, cancel any time.",
  alternates: { canonical: "/membership" },
};

/** Shown while the API can't be reached: the page still explains the offer. */
const FALLBACK: PlusOfferOut = {
  on_sale: false,
  product_name: "ApprovalReady Plus",
  description: "",
  amount_cents: null,
  currency: null,
  interval: null,
  trial_days: 30,
  reminder_days: 7,
};

function faq(offer: PlusOfferOut, price: string | null) {
  const days = offer.trial_days;
  const then = price
    ? `${price}, charged automatically`
    : "the monthly price, charged automatically";
  return [
    {
      q: "Will I be charged today?",
      a:
        days > 0
          ? `No. You add your card today and pay nothing for ${days} days. On day ${days + 1} it becomes ${then}.`
          : `Your membership starts straight away at ${then}.`,
    },
    {
      q: "Why do you need my card for a free month?",
      a: "So your project plans keep going without a break when the free month ends. Your card goes straight to Stripe, our payment provider; we never see or store it.",
    },
    {
      q: "Will you remind me before you charge?",
      a: `Yes. We email you ${offer.reminder_days} days before the first charge with the date and the amount.`,
    },
    {
      q: "How do I cancel?",
      a: "Go to Billing in your account and press Manage billing, then Cancel. It takes under a minute. Cancel before the free month ends and you pay nothing.",
    },
    {
      q: "Can I have another free month later?",
      a: "The free month is once per account. You can rejoin any time at the normal price.",
    },
    {
      q: "Do prices include GST?",
      a: "Yes. Every price on ApprovalReady includes GST, and you get a tax invoice for each payment.",
    },
  ];
}

export default async function MembershipPage() {
  await connection(); // the price is set by staff, so read it on each visit
  const result = await publicGet<PlusOfferOut>("/billing/membership");
  const offer = result.ok ? result.data : FALLBACK;
  const price = plusPrice(offer);
  const days = offer.trial_days;
  const start = offer.on_sale ? "/membership/start" : "/register";
  const cta = offer.on_sale
    ? days > 0
      ? "Start my free month"
      : "Join now"
    : "Create a free account";
  return (
    <>
      <SiteHeader />
      <main>
        <section className="hero" aria-labelledby="plus-title">
          <div className="container hero-grid">
            <div className="hero-copy">
              <p className="eyebrow">ApprovalReady Plus</p>
              <h1 id="plus-title">
                {days > 0
                  ? days === 30
                    ? "Your first month free"
                    : `${days} days free`
                  : "Every project, managed"}
              </h1>
              <p className="hero-lede">
                Turn your approval checklist into a plan you can actually follow: every step in
                order, with the forms, fees, contacts and dates, and checked local partners for the
                parts you can&apos;t do yourself.
              </p>
              <div className="button-row">
                <Link className="button button-on-inverse button-large" href={start}>
                  {cta}
                </Link>
              </div>
              <p className="plus-fine-print">
                {offer.on_sale
                  ? days > 0
                    ? `$0 today. Then ${price ?? "the monthly price"}. Card needed. Cancel any time before day ${days + 1} and pay nothing.`
                    : `${price ?? ""}. Cancel any time.`
                  : "Opening soon. Create a free account now and use everything else free."}
              </p>
            </div>
            <TrialTimeline offer={offer} trial={days > 0} title="What you pay, and when" />
          </div>
        </section>

        <section className="section" aria-labelledby="plus-get-title">
          <div className="container">
            <p className="eyebrow">What you get</p>
            <h2 id="plus-get-title" className="section-heading">
              Everything to get each approval done
            </h2>
            <ul className="plus-benefits" aria-label="What's included">
              {PLUS_BENEFITS.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </div>
        </section>

        <section className="section section-tinted" aria-labelledby="plus-how-title">
          <div className="container">
            <p className="eyebrow">How the free month works</p>
            <h2 id="plus-how-title" className="section-heading">
              No surprises
            </h2>
            <ol className="how-steps">
              <li>
                <h3>Add your card</h3>
                <p>On Stripe&apos;s secure page. Nothing is charged today.</p>
              </li>
              <li>
                <h3>Use everything{days > 0 ? ` for ${days} days` : ""}</h3>
                <p>Start a project plan for every project you have, at no extra cost.</p>
              </li>
              <li>
                <h3>Keep it, or cancel</h3>
                <p>
                  We remind you {offer.reminder_days} days before the first charge. Do nothing and
                  it carries on{price ? ` at ${price}` : ""}, or cancel in under a minute.
                </p>
              </li>
            </ol>
          </div>
        </section>

        <section className="section" aria-labelledby="plus-faq-title">
          <div className="container">
            <h2 id="plus-faq-title" className="section-heading">
              Questions
            </h2>
            <dl className="plus-faq">
              {faq(offer, price).map((item) => (
                <div key={item.q}>
                  <dt>{item.q}</dt>
                  <dd>{item.a}</dd>
                </div>
              ))}
            </dl>
          </div>
        </section>

        <section className="container" aria-labelledby="plus-cta-title">
          <div className="cta-band">
            <h2 id="plus-cta-title">
              {days > 0 ? "Try it free for a month" : "Get every project done"}
            </h2>
            <p>
              Already have an account? Sign in and it takes about a minute. New here? Create an
              account first, then come back to this page.
            </p>
            <Link className="button button-large" href={start}>
              {cta}
            </Link>
          </div>
        </section>
      </main>
      <SiteFooter />
    </>
  );
}
