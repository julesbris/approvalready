import type { ApprovalGuideOut } from "@approvalready/shared-types";

import { phoneHref } from "@/lib/approvalGuides";
import { formatDate } from "@/lib/questionnaire";

function External({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a href={href} rel="noopener noreferrer" target="_blank">
      {children}
    </a>
  );
}

function CheckedBadge({ guide }: { guide: ApprovalGuideOut }) {
  return guide.checked.verified ? (
    <span className="status status-verified">
      Checked by our team
      {guide.checked.verified_at ? ` ${formatDate(guide.checked.verified_at)}` : ""}
    </span>
  ) : (
    <span className="status confidence-review_required">Not yet checked by our team</span>
  );
}

/** One approval: what to have ready, the steps in order, fees, contacts and what goes wrong. */
export function ApprovalGuideCard({
  guide,
  number,
  open = false,
}: {
  guide: ApprovalGuideOut;
  number: number;
  open?: boolean;
}) {
  const titleId = `guide-${guide.kind.toLowerCase()}`;
  return (
    <details className="guide" id={titleId} open={open}>
      <summary>
        <span className="guide-number" aria-hidden="true">
          {number}
        </span>
        <span className="guide-summary">
          <span className="guide-title">{guide.title}</span>
          <span className="muted">
            {guide.authority}
            {guide.timeframe ? ` · ${guide.timeframe}` : ""}
          </span>
        </span>
      </summary>
      <div className="guide-body">
        <div className="guide-head">
          <CheckedBadge guide={guide} />
        </div>
        <p>{guide.summary}</p>
        {guide.timeframe || guide.cost_summary ? (
          <dl className="review-list">
            {guide.timeframe ? (
              <div>
                <dt>How long</dt>
                <dd>{guide.timeframe}</dd>
              </div>
            ) : null}
            {guide.cost_summary ? (
              <div>
                <dt>What it costs</dt>
                <dd>{guide.cost_summary}</dd>
              </div>
            ) : null}
          </dl>
        ) : null}

        {guide.before_you_start.length > 0 ? (
          <>
            <h4 className="subsection-title">Before you start</h4>
            <ul className="guide-list">
              {guide.before_you_start.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </>
        ) : null}

        <h4 className="subsection-title">Step by step</h4>
        <ol className="guide-steps">
          {guide.steps.map((step) => (
            <li key={step.title}>
              <p className="guide-step-title">{step.title}</p>
              <p>{step.detail}</p>
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

        {guide.fees.length > 0 ? (
          <>
            <h4 className="subsection-title">Fees and charges</h4>
            <table className="guide-fees">
              <caption className="muted">
                As published by the authority when we checked on {formatDate(guide.checked_on)}.
                Fees usually change each 1 July.
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
          </>
        ) : null}

        {guide.watch_out.length > 0 ? (
          <div className="notice notice-warning">
            <p className="guide-step-title">Watch out for</p>
            <ul className="guide-list">
              {guide.watch_out.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        ) : null}

        {guide.contacts.length > 0 ? (
          <>
            <h4 className="subsection-title">Who to contact</h4>
            <ul className="guide-contacts">
              {guide.contacts.map((c) => {
                const tel = c.phone ? phoneHref(c.phone) : null;
                return (
                  <li key={c.name}>
                    <strong>{c.name}</strong>
                    {c.phone ? (
                      <span>
                        {" "}
                        · {tel ? <a href={tel}>{c.phone}</a> : c.phone}
                      </span>
                    ) : null}
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
          </>
        ) : null}

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
        <details className="guide-more">
          <summary>Where this came from</summary>
          <ul>
            {guide.sources.map((source) => (
              <li key={source.url}>
                <External href={source.url}>{source.title}</External>
              </li>
            ))}
          </ul>
          <p className="muted">
            Gathered from official websites on {formatDate(guide.checked_on)}.
          </p>
        </details>
      </div>
    </details>
  );
}

/**
 * Every approval an assessment named, as one plan in the order to do them: an overview of
 * how long each takes and what it costs, then each approval's steps, fees and contacts.
 */
export function ApprovalPlan({ guides }: { guides: ApprovalGuideOut[] }) {
  if (guides.length === 0) return null;
  const unchecked = guides.some((g) => !g.checked.verified);
  return (
    <section className="panel approval-plan" aria-labelledby="plan-title">
      <h2 id="plan-title" className="section-title">
        Your step-by-step plan
      </h2>
      <p>
        Everything the assessment found you may need, in the order to do it, with the forms,
        fees, timeframes and who to contact for each.
      </p>
      {unchecked ? (
        <p className="muted">
          Gathered from official government websites. Parts marked &quot;Not yet checked by our
          team&quot; haven&apos;t been reviewed by a person yet, so confirm fees and forms with the
          authority before you pay or lodge.
        </p>
      ) : null}
      <table className="guide-fees plan-overview">
        <thead>
          <tr>
            <th scope="col">Step</th>
            <th scope="col">How long</th>
            <th scope="col">Cost</th>
          </tr>
        </thead>
        <tbody>
          {guides.map((g, i) => (
            <tr key={g.kind}>
              <td>
                <a href={`#guide-${g.kind.toLowerCase()}`}>
                  {i + 1}. {g.title}
                </a>
              </td>
              <td>{g.timeframe ?? "See steps"}</td>
              <td>{g.cost_summary ?? "See fees"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="guide-stack">
        {guides.map((g, i) => (
          <ApprovalGuideCard key={g.kind} guide={g} number={i + 1} open={i === 0} />
        ))}
      </div>
    </section>
  );
}
