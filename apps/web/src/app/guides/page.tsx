import type { Metadata } from "next";
import Link from "next/link";

import { PublicShell } from "@/components/public/PublicShell";
import { GUIDES } from "@/lib/guides";
import { GUIDE_STATES, PUBLIC_GUIDES, SCENARIOS } from "@/lib/publicGuides";

export const metadata: Metadata = {
  title: "Approval guides for every Australian state and territory",
  description:
    "Free step-by-step guides to building, business, selling, renting, boating and import approvals in every state and territory, with official forms, fees and contacts.",
  alternates: { canonical: "/guides" },
};

function count(segment: string): number {
  return PUBLIC_GUIDES.filter((g) => g.state.segment === segment).length;
}

export default function GuidesPage() {
  return (
    <PublicShell>
      <div className="guides-index">
        <header className="guides-head">
          <p className="eyebrow">Sources, not guesses</p>
          <h1 id="guides-title">Approval guides</h1>
          <p className="lede">
            {PUBLIC_GUIDES.length} step-by-step guides to the approvals, licences and
            registrations people need in Australia: every step, official form, fee, timeframe
            and contact, with a link to every source.
          </p>
        </header>
        <section className="guide-group" aria-labelledby="by-state">
          <h2 id="by-state">Guides by state and territory</h2>
          <ul className="guide-cards state-cards">
            {GUIDE_STATES.map((s) => (
              <li key={s.segment}>
                <Link className="guide-card" href={`/guides/${s.segment}`}>
                  <span className="guide-card-area">{count(s.segment)} guides</span>
                  <h3>{s.name}</h3>
                  <span className="guide-card-cta">See the guides</span>
                </Link>
              </li>
            ))}
          </ul>
          <p className="muted">
            Covers {SCENARIOS.map((s) => s.name.toLowerCase()).join(", ")}.
          </p>
        </section>
        <h2 className="guide-group-title" id="explainers">
          Explainers
        </h2>
        <ul className="guide-cards" aria-labelledby="explainers">
          {GUIDES.map((g) => (
            <li key={g.slug}>
              <Link className="guide-card" href={`/guides/${g.slug}`}>
                <span className="guide-card-area">{g.area}</span>
                <h3>{g.title}</h3>
                <p>{g.description}</p>
                <span className="guide-card-cta">Read the guide</span>
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </PublicShell>
  );
}
