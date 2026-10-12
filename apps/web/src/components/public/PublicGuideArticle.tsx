import Link from "next/link";

import { FormLinks, FormList, FormText } from "@/components/guidance/FormText";
import { phoneHref } from "@/lib/approvalGuides";
import {
  CARD_SIZES,
  cardAlt,
  cardPath,
  guideFaqs,
  pageTitle,
  placeName,
  type PublicGuide,
  relatedGuides,
  scenario,
} from "@/lib/publicGuides";
import { formatDate } from "@/lib/questionnaire";

function External({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a href={href} rel="noopener noreferrer" target="_blank">
      {children}
    </a>
  );
}

/**
 * A step-by-step approval guide as a public page: the direct answer first (what search and
 * answer engines quote), then the key facts, every step with its form, cost and timeframe,
 * fees, contacts, common mistakes, questions people ask, and the official sources it came
 * from with the date they were read.
 */
export function PublicGuideArticle({ guide }: { guide: PublicGuide }) {
  const vertical = guide.verticals[0] ?? "PLANNING";
  const topic = scenario(vertical);
  const faqs = guideFaqs(guide);
  const related = relatedGuides(guide);
  const checked = formatDate(guide.checked_on);
  return (
    <article className="public-guide" aria-labelledby="guide-title">
      <nav aria-label="Breadcrumb" className="breadcrumb">
        <Link href="/guides">Guides</Link> ·{" "}
        <Link href={`/guides/${guide.state.segment}`}>{guide.state.name}</Link>
        {topic ? (
          <>
            {" "}
            ·{" "}
            <Link href={`/guides/${guide.state.segment}#${vertical.toLowerCase()}`}>
              {topic.name}
            </Link>
          </>
        ) : null}
      </nav>
      <h1 id="guide-title" className="page-title">
        {pageTitle(guide)}
      </h1>
      <p className="muted guide-byline">
        By the ApprovalReady team · Gathered from official sources, last checked{" "}
        <time dateTime={guide.checked_on}>{checked}</time>
      </p>

      <FormLinks forms={guide.forms}>
        <section className="answer-box" aria-labelledby="quick-answer">
          <h2 id="quick-answer">Quick answer</h2>
          <p>
            <FormText text={guide.summary} />
          </p>
        </section>

        <dl className="guide-facts">
          {guide.cost_summary ? (
            <div>
              <dt>What it costs</dt>
              <dd>{guide.cost_summary}</dd>
            </div>
          ) : null}
          {guide.timeframe ? (
            <div>
              <dt>How long it takes</dt>
              <dd>{guide.timeframe}</dd>
            </div>
          ) : null}
          <div>
            <dt>Who issues it</dt>
            <dd>{guide.authority}</dd>
          </div>
          <div>
            <dt>Where it applies</dt>
            <dd>{placeName(guide.state)}</dd>
          </div>
        </dl>

        <figure className="guide-figure">
          {/* eslint-disable-next-line @next/next/no-img-element -- generated JPEG card */}
          <img
            src={cardPath(guide, "wide")}
            alt={cardAlt(guide)}
            width={CARD_SIZES.wide.width}
            height={CARD_SIZES.wide.height}
          />
        </figure>

        <nav className="guide-toc" aria-label="On this page">
          <p className="guide-step-title">On this page</p>
          <ol>
            {guide.before_you_start.length > 0 ? (
              <li>
                <a href="#before-you-start">Before you start</a>
              </li>
            ) : null}
            <li>
              <a href="#steps">Step by step</a>
            </li>
            {guide.fees.length > 0 ? (
              <li>
                <a href="#fees">Fees</a>
              </li>
            ) : null}
            {guide.contacts.length > 0 ? (
              <li>
                <a href="#contacts">Who to contact</a>
              </li>
            ) : null}
            <li>
              <a href="#questions">Common questions</a>
            </li>
            <li>
              <a href="#sources">Sources</a>
            </li>
          </ol>
        </nav>

        {guide.before_you_start.length > 0 ? (
          <section aria-labelledby="before-you-start">
            <h2 id="before-you-start">Before you start</h2>
            <ul className="guide-list">
              {guide.before_you_start.map((item) => (
                <li key={item}>
                  <FormText text={item} />
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {guide.forms.length > 0 ? (
          <section aria-labelledby="forms">
            <FormList forms={guide.forms} level={2} />
          </section>
        ) : null}

        <section aria-labelledby="steps">
          <h2 id="steps">Step by step</h2>
          <ol className="guide-steps public-steps">
            {guide.steps.map((step, i) => (
              <li key={step.title} id={`step-${i + 1}`}>
                <h3 className="guide-step-title">
                  <FormText text={step.title} />
                </h3>
                <p>
                  <FormText text={step.detail} />
                </p>
                {step.timeframe || step.cost || step.form || step.url ? (
                  <p className="guide-step-meta muted">
                    {[
                      step.timeframe ? <span key="t">Time: {step.timeframe}</span> : null,
                      step.cost ? <span key="c">Cost: {step.cost}</span> : null,
                      step.form ? (
                        <span key="f">
                          Form: <External href={step.form.url}>{step.form.name}</External>
                        </span>
                      ) : null,
                      step.url ? (
                        <span key="u">
                          <External href={step.url}>Official page</External>
                        </span>
                      ) : null,
                    ].filter(Boolean)}
                  </p>
                ) : null}
              </li>
            ))}
          </ol>
        </section>

        {guide.fees.length > 0 ? (
          <section aria-labelledby="fees">
            <h2 id="fees">Fees</h2>
            <table className="guide-fees">
              <caption className="muted">
                As published by the authority when we checked on {checked}. Fees usually change
                each 1 July.
              </caption>
              <thead>
                <tr>
                  <th scope="col">What for</th>
                  <th scope="col">Amount</th>
                </tr>
              </thead>
              <tbody>
                {guide.fees.map((fee) => (
                  <tr key={`${fee.label}-${fee.amount}`}>
                    <td>
                      {fee.label}
                      {fee.note ? <span className="muted"> ({fee.note})</span> : null}
                    </td>
                    <td className="guide-amount">{fee.amount}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        ) : null}

        {guide.watch_out.length > 0 ? (
          <section aria-labelledby="watch-out" className="notice notice-warning">
            <h2 id="watch-out">Watch out for</h2>
            <ul className="guide-list">
              {guide.watch_out.map((item) => (
                <li key={item}>
                  <FormText text={item} />
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {guide.contacts.length > 0 ? (
          <section aria-labelledby="contacts">
            <h2 id="contacts">Who to contact</h2>
            <ul className="guide-contacts">
              {guide.contacts.map((c) => {
                const tel = c.phone ? phoneHref(c.phone) : null;
                return (
                  <li key={c.name}>
                    <strong>{c.name}</strong>
                    {c.phone ? <span> · {tel ? <a href={tel}>{c.phone}</a> : c.phone}</span> : null}
                    {c.email ? (
                      <span>
                        {" "}
                        · <a href={`mailto:${c.email}`}>{c.email}</a>
                      </span>
                    ) : null}
                    {c.url ? (
                      <span>
                        {" "}
                        · <External href={c.url}>Website</External>
                      </span>
                    ) : null}
                    {c.hours ? <span className="muted"> · {c.hours}</span> : null}
                    {c.note ? <span className="muted"> · {c.note}</span> : null}
                  </li>
                );
              })}
            </ul>
          </section>
        ) : null}
      </FormLinks>

      <section aria-labelledby="questions">
        <h2 id="questions">Common questions</h2>
        <div className="guide-faqs">
          {faqs.map((f) => (
            <div key={f.question}>
              <h3>{f.question}</h3>
              <p>{f.answer}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="principle guide-cta">
        <h2>Get the checklist for your situation</h2>
        <p>
          Answer a few questions and ApprovalReady shows every approval you need, in order, with
          the forms, fees and contacts for each. Free to start.
        </p>
        <p>
          <Link className="button" href={`/projects/new?vertical=${vertical}`}>
            Start your free check
          </Link>
        </p>
      </section>

      <section aria-labelledby="sources">
        <h2 id="sources">Sources and how we checked</h2>
        <p>
          The ApprovalReady team gathered this guide from the official pages below on {checked},
          and our systems re-read them every week for changes. Every fee, form and timeframe
          above comes from these pages.
        </p>
        <ul className="sources">
          {guide.sources.map((s) => (
            <li key={s.url}>
              <External href={s.url}>{s.title}</External>
            </li>
          ))}
        </ul>
        {guide.gaps.length > 0 ? (
          <details className="guide-more">
            <summary>What we couldn&apos;t confirm</summary>
            <ul>
              {guide.gaps.map((gap) => (
                <li key={gap}>{gap}</li>
              ))}
            </ul>
          </details>
        ) : null}
        <p className="muted">
          This is general information, not legal advice. Rules and fees change, so check the
          official page before you apply or pay.
        </p>
      </section>

      {related.length > 0 ? (
        <section aria-labelledby="related">
          <h2 id="related">Related guides</h2>
          <ul className="related-guides">
            {related.map((g) => (
              <li key={g.kind}>
                <Link href={g.path}>{g.title}</Link>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </article>
  );
}
