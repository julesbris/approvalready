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
      <section className="hero" aria-labelledby="guides-title">
        <h1 id="guides-title">Guides</h1>
        <p>
          Plain-language summaries of what the rules say, with a link to every source and a note
          of how far we have checked it.
        </p>
      </section>
      <ul className="products" aria-label="Guides">
        {GUIDES.map((g) => (
          <li key={g.slug} className="product">
            <h2>
              <Link href={`/guides/${g.slug}`}>{g.title}</Link>
            </h2>
            <p>{g.description}</p>
          </li>
        ))}
      </ul>
    </PublicShell>
  );
}
