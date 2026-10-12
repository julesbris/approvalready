import Link from "next/link";

import {
  firstSentence,
  GUIDE_STATES,
  type GuideState,
  guidesFor,
  NATIONAL,
  placeName,
  type PublicGuide,
  SCENARIOS,
} from "@/lib/publicGuides";

function GuideList({ guides }: { guides: PublicGuide[] }) {
  return (
    <ul className="guide-cards">
      {guides.map((g) => (
        <li key={g.kind}>
          <Link className="guide-card" href={g.path}>
            <span className="guide-card-area">{g.publisher}</span>
            <h3>{g.title}</h3>
            <p>{firstSentence(g.summary, 200)}</p>
            <span className="guide-card-cta">Read the guide</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

/**
 * Every guide for one state or territory, grouped by what someone is trying to do, with the
 * Australia-wide guides that also apply listed after the state's own.
 */
export function StateGuides({ state }: { state: GuideState }) {
  const place = placeName(state);
  const sections = SCENARIOS.map((s) => ({ scenario: s, ...guidesFor(state.segment, s.vertical) }))
    .filter((s) => s.local.length + s.national.length > 0);
  const total = sections.reduce((n, s) => n + s.local.length, 0);
  return (
    <div className="guides-index">
      <nav aria-label="Breadcrumb" className="breadcrumb">
        <Link href="/guides">Guides</Link> · {state.name}
      </nav>
      <header className="guides-head">
        <p className="eyebrow">{state.name}</p>
        <h1 id="state-title">
          {state.segment === NATIONAL
            ? "Australia-wide approvals: step-by-step guides"
            : `Approvals in ${place}: step-by-step guides`}
        </h1>
        <p className="lede">
          {total} free guides to the approvals, licences and registrations you may need in{" "}
          {place}, each with the steps in order, the official forms, fees, timeframes and who to
          contact, gathered from official government sources.
        </p>
        <ul className="guide-jump" aria-label="Jump to">
          {sections.map(({ scenario }) => (
            <li key={scenario.vertical}>
              <a href={`#${scenario.vertical.toLowerCase()}`}>{scenario.name}</a>
            </li>
          ))}
        </ul>
      </header>
      {sections.map(({ scenario, local, national }) => (
        <section
          key={scenario.vertical}
          id={scenario.vertical.toLowerCase()}
          className="guide-group"
          aria-labelledby={`${scenario.vertical.toLowerCase()}-title`}
        >
          <h2 id={`${scenario.vertical.toLowerCase()}-title`}>{scenario.name}</h2>
          <p className="muted">
            What you may need to {scenario.doing} in {place}.
          </p>
          {local.length > 0 ? <GuideList guides={local} /> : null}
          {national.length > 0 ? (
            <>
              <h3 className="subsection-title">Also needed Australia-wide</h3>
              <GuideList guides={national} />
            </>
          ) : null}
        </section>
      ))}
      <section className="guide-group" aria-labelledby="other-states">
        <h2 id="other-states">Guides for other states and territories</h2>
        <ul className="guide-jump">
          {GUIDE_STATES.filter((s) => s.segment !== state.segment).map((s) => (
            <li key={s.segment}>
              <Link href={`/guides/${s.segment}`}>{s.name}</Link>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
