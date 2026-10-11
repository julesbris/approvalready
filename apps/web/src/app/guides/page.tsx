import type { Metadata } from "next";
import Link from "next/link";

import { PublicShell } from "@/components/public/PublicShell";
import { GUIDES } from "@/lib/guides";

export const metadata: Metadata = {
  title: "Guides",
  description: "Plain-language guides to approvals, with the sources behind every point.",
  alternates: { canonical: "/guides" },
};

export default function GuidesPage() {
  return (
    <PublicShell>
      <div className="guides-index">
        <header className="guides-head">
          <p className="eyebrow">Sources, not guesses</p>
          <h1 id="guides-title">Guides</h1>
          <p className="lede">
            Plain-language summaries of what the rules say, with a link to every source and a
            note of how far we have checked it.
          </p>
        </header>
        <ul className="guide-cards" aria-labelledby="guides-title">
          {GUIDES.map((g) => (
            <li key={g.slug}>
              <Link className="guide-card" href={`/guides/${g.slug}`}>
                <span className="guide-card-area">{g.area}</span>
                <h2>{g.title}</h2>
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
