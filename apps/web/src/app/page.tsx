import type { Confidence } from "@approvalready/shared-types";
import Link from "next/link";

import { ProductIcon } from "@/components/public/ProductIcon";
import { SiteFooter } from "@/components/public/SiteFooter";
import { SiteHeader } from "@/components/public/SiteHeader";
import { CONFIDENCE_HELP, CONFIDENCE_LABELS } from "@/lib/assessment";
import { defaultBrand } from "@/lib/brand";

const LEVELS: Confidence[] = ["VERIFIED", "LIKELY", "REVIEW_REQUIRED", "UNKNOWN"];

const STEPS = [
  {
    title: "Tell us about it",
    text: "Answer plain-English questions about your property, business, vessel or organisation.",
  },
  {
    title: "See what applies",
    text: "Get the approvals, licences and grants that apply, each linked to its published source.",
  },
  {
    title: "Get it ready",
    text: "Track tasks, keep your evidence in one place, and ask a professional when you need one.",
  },
];

/** The brand pattern: one row of roof chevrons, the symbol's roofline at 30 degrees. */
function RoofChevrons() {
  return (
    <svg className="roof-chevrons" viewBox="0 0 384 32" aria-hidden="true" focusable="false">
      {Array.from({ length: 8 }, (_, i) => (
        <path key={i} d={`M${8 + i * 48} 28 L${24 + i * 48} 4 L${40 + i * 48} 28`} />
      ))}
    </svg>
  );
}

/** An illustration of a result, so visitors see what they get before they sign up. */
function ExampleResult() {
  const rows: { name: string; level: Confidence }[] = [
    { name: "Building approval", level: "VERIFIED" },
    { name: "Plumbing approval", level: "LIKELY" },
    { name: "Council fees", level: "REVIEW_REQUIRED" },
  ];
  return (
    <aside className="example-card" aria-label="Example result">
      <div className="example-head">
        <div>
          <p className="example-ref">Example · PlanningReady</p>
          <p className="example-title">Granny flat in the backyard</p>
        </div>
        <span className="status status-assessed">Assessed</span>
      </div>
      <ul className="example-rows">
        {rows.map((row) => (
          <li key={row.name}>
            <span>{row.name}</span>
            <span className={`status confidence confidence-${row.level.toLowerCase()}`}>
              {CONFIDENCE_LABELS[row.level]}
            </span>
          </li>
        ))}
      </ul>
      <p className="example-foot">Every finding links to the source it is based on.</p>
    </aside>
  );
}

export default function HomePage() {
  const brand = defaultBrand;
  return (
    <>
      <SiteHeader />
      <main>
        <section className="hero" aria-labelledby="hero-title">
          <div className="container hero-grid">
            <div className="hero-copy">
              <RoofChevrons />
              <p className="eyebrow">Approvals, licences and grants in Australia</p>
              <h1 id="hero-title">{brand.tagline}</h1>
              <p className="hero-lede">{brand.description}</p>
              <div className="button-row">
                <Link className="button button-on-inverse button-large" href="/register">
                  Get started
                </Link>
                <Link className="button button-outline-inverse button-large" href="/guides">
                  Read the guides
                </Link>
              </div>
            </div>
            <ExampleResult />
          </div>
        </section>

        <section className="section" aria-labelledby="products-title">
          <div className="container">
            <p className="eyebrow">One platform for every approval</p>
            <h2 id="products-title" className="section-heading">
              Start with the question you have
            </h2>
            <ul className="products" aria-label="Product areas">
              {brand.products.map((product) => (
                <li key={product.key} className="product">
                  <ProductIcon vertical={product.key} />
                  <h3>{product.name}</h3>
                  <p>{product.question}</p>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section className="section section-tinted" aria-labelledby="trust-title">
          <div className="container">
            <p className="eyebrow">Sources, not guesses</p>
            <h2 id="trust-title" className="section-heading">
              Every answer shows how sure we are
            </h2>
            <p className="principle">
              Every result is based on published regulatory sources and shows how confident we
              are: verified, likely, review required, or unknown. We never guess at approvals,
              fees or dates.
            </p>
            <ul className="confidence-grid" aria-label="Confidence levels">
              {LEVELS.map((level) => (
                <li key={level}>
                  <span className={`status confidence confidence-${level.toLowerCase()}`}>
                    {CONFIDENCE_LABELS[level]}
                  </span>
                  <p>{CONFIDENCE_HELP[level]}</p>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section className="section" aria-labelledby="how-title">
          <div className="container">
            <p className="eyebrow">How it works</p>
            <h2 id="how-title" className="section-heading">
              From first question to ready to apply
            </h2>
            <ol className="how-steps">
              {STEPS.map((step) => (
                <li key={step.title}>
                  <h3>{step.title}</h3>
                  <p>{step.text}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section className="container" aria-labelledby="cta-title">
          <div className="cta-band">
            <h2 id="cta-title">Find out what applies to you</h2>
            <p>Create an account, start a project and see which approvals apply.</p>
            <Link className="button button-large" href="/register">
              Get started
            </Link>
          </div>
        </section>
      </main>
      <SiteFooter />
    </>
  );
}
