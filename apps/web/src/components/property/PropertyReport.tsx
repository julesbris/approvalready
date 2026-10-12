"use client";

import type { PropertyReportOut, ReportSection } from "@approvalready/shared-types";
import { useEffect, useState } from "react";

import { apiRequest } from "@/lib/client-api";

type Props = { organisationId: string; propertyId: string };

type State =
  | { status: "loading" }
  | { status: "failed"; message: string }
  | { status: "ready"; report: PropertyReportOut };

export function distanceWords(metres: number): string {
  return metres < 1000 ? `${Math.round(metres / 10) * 10} m` : `${(metres / 1000).toFixed(1)} km`;
}

function Section({ section }: { section: ReportSection }) {
  return (
    <section className="panel report-section" aria-labelledby={`report-${section.key}`}>
      <h2 id={`report-${section.key}`} className="section-title">
        {section.title}
      </h2>
      <p className="muted">{section.intro}</p>
      {section.status === "unavailable" ? (
        <p className="notice notice-warning">
          We couldn&apos;t check this just now. Open the report again later.
        </p>
      ) : section.status === "partial" ? (
        <p className="hint">Some of this couldn&apos;t be checked just now.</p>
      ) : null}
      {section.facts.length > 0 ? (
        <dl className="report-facts">
          {section.facts.map((f) => (
            <div key={f.label}>
              <dt>{f.label}</dt>
              <dd>
                <strong>{f.value}</strong>
                {f.compare ? <span className="muted"> {f.compare}</span> : null}
                {f.note ? <span className="hint"> {f.note}</span> : null}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}
      {section.items.length > 0 ? (
        <ul className="report-items">
          {section.items.map((item, i) => (
            <li key={`${item.label}-${i}`}>
              <span>
                {item.url ? (
                  <a href={item.url} target="_blank" rel="noreferrer">
                    {item.label}
                  </a>
                ) : (
                  item.label
                )}
                {item.detail ? <span className="muted"> · {item.detail}</span> : null}
              </span>
              {item.distance_m != null ? (
                <span className="report-distance">{distanceWords(item.distance_m)}</span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {section.links.length > 0 ? (
        <>
          <h3 className="subsection-title">Where to check</h3>
          <ul className="report-links">
            {section.links.map((l) => (
              <li key={l.url}>
                <a href={l.url} target="_blank" rel="noreferrer">
                  {l.label}
                </a>
                <span className="muted"> {l.why}</span>
              </li>
            ))}
          </ul>
        </>
      ) : null}
      {section.sources.length > 0 ? (
        <p className="hint">
          Source:{" "}
          {section.sources.map((s, i) => (
            <span key={s.name}>
              {i > 0 ? "; " : ""}
              <a href={s.url} target="_blank" rel="noreferrer">
                {s.name}
              </a>{" "}
              ({s.as_at})
            </span>
          ))}
        </p>
      ) : null}
    </section>
  );
}

/** The free property report: gathered from public data when opened (it takes a few
 * seconds), with a branded PDF to keep or send. */
export function PropertyReport({ organisationId, propertyId }: Props) {
  const [state, setState] = useState<State>({ status: "loading" });
  const path = `/organisations/${organisationId}/properties/${propertyId}/report`;

  useEffect(() => {
    let live = true;
    apiRequest<PropertyReportOut>("GET", path).then((result) => {
      if (!live) return;
      setState(
        result.ok
          ? { status: "ready", report: result.data }
          : { status: "failed", message: result.message },
      );
    });
    return () => {
      live = false;
    };
  }, [path]);

  if (state.status === "loading") {
    return (
      <p className="muted" role="status">
        Gathering government, census, school, crime and local data for this property…
      </p>
    );
  }
  if (state.status === "failed") {
    return <p className="form-error">{state.message}</p>;
  }
  const { report } = state;
  return (
    <div className="property-report">
      <section className="panel report-cover" aria-label="At a glance">
        <p className="report-address">{report.address}</p>
        <p className="muted">
          {[report.suburb, report.council].filter(Boolean).join(" · ")}
        </p>
        {report.headline.length > 0 ? (
          <ul>
            {report.headline.map((h) => (
              <li key={h}>{h}</li>
            ))}
          </ul>
        ) : null}
        <div className="button-row tight">
          <a className="button" href={`/api/v1${path}.pdf`} download>
            Download PDF
          </a>
        </div>
        <p className="hint">Free with your account. Every figure says where it comes from.</p>
      </section>
      {report.sections.map((s) => (
        <Section key={s.key} section={s} />
      ))}
      <p className="hint">{report.disclaimer}</p>
    </div>
  );
}
