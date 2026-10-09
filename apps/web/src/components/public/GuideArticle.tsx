import Link from "next/link";

import type { Guide } from "@/lib/guides";
import { formatDate } from "@/lib/questionnaire";

/** A sourced guide: what the sources say, how far they've been checked, and what's left out. */
export function GuideArticle({ guide }: { guide: Guide }) {
  return (
    <article className="guide" aria-labelledby="guide-title">
      <p className="breadcrumb">
        <Link href="/guides">Guides</Link> · {guide.area}
      </p>
      <h1 id="guide-title" className="page-title">
        {guide.title}
      </h1>
      <p className="lede">{guide.description}</p>
      <p className="notice">
        {guide.verification === "VERIFIED"
          ? `Our team checked these sources on ${formatDate(guide.checkedOn)}.`
          : `Summarised from the sources below on ${formatDate(guide.checkedOn)}. Our team has not yet verified them against the current planning scheme, and council's fact sheets date from 2021.`}{" "}
        This is general information, not legal or planning advice. Check with Cairns Regional
        Council or a town planner before you rely on it.
      </p>
      {guide.sections.map((section) => (
        <section key={section.heading}>
          <h2 className="section-title">{section.heading}</h2>
          {section.paragraphs.map((text) => (
            <p key={text}>{text}</p>
          ))}
          {section.points ? (
            <ul>
              {section.points.map((point) => (
                <li key={point}>{point}</li>
              ))}
            </ul>
          ) : null}
        </section>
      ))}
      <section>
        <h2 className="section-title">What this guide doesn&apos;t cover</h2>
        <ul>
          {guide.notCovered.map((text) => (
            <li key={text}>{text}</li>
          ))}
        </ul>
      </section>
      <section aria-labelledby="guide-sources">
        <h2 id="guide-sources" className="section-title">
          Sources
        </h2>
        <ul className="sources">
          {guide.sources.map((s) => (
            <li key={s.url}>
              <a href={s.url} rel="noopener noreferrer" target="_blank">
                {s.title}
              </a>{" "}
              <span className="muted">
                {s.publisher} · {s.version}
              </span>
            </li>
          ))}
        </ul>
      </section>
      <section className="principle">
        <p>
          Want to know what applies to your site? <Link href="/register">Create an account</Link>,
          answer a few questions about your project and get an assessment that shows the source
          and confidence behind every result.
        </p>
      </section>
    </article>
  );
}
