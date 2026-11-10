"use client";

import type {
  PropertyReportOut,
  ReportChart,
  ReportScore,
  ReportSection,
} from "@approvalready/shared-types";
import { useEffect, useId, useState } from "react";

import { FinanceCallout } from "@/components/finance/FinanceCallout";
import { apiRequest } from "@/lib/client-api";

type Props = { organisationId: string; propertyId: string };

type State =
  | { status: "loading" }
  | { status: "failed"; message: string }
  | { status: "ready"; report: PropertyReportOut };

export function distanceWords(metres: number): string {
  return metres < 1000
    ? `${Math.round(metres / 10) * 10} m`
    : `${(metres / 1000).toFixed(1)} km`;
}

/** Monthly repayment on a principal-and-interest loan. */
export function monthlyRepayment(
  loan: number,
  ratePercent: number,
  years: number,
): number {
  const n = Math.round(years * 12);
  if (loan <= 0 || n <= 0) return 0;
  const r = ratePercent / 100 / 12;
  if (r <= 0) return loan / n;
  return (loan * r) / (1 - (1 + r) ** -n);
}

function dollars(value: number): string {
  return `$${Math.round(value).toLocaleString("en-AU")}`;
}

function NumberField({
  label,
  value,
  onChange,
  step,
  suffix,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  step: number;
  suffix?: string;
}) {
  const id = useId();
  return (
    <div className="repayment-field">
      <label htmlFor={id}>{label}</label>
      <span>
        <input
          id={id}
          type="number"
          inputMode="decimal"
          min={0}
          step={step}
          value={Number.isFinite(value) ? value : ""}
          onChange={(e) => onChange(e.target.valueAsNumber)}
        />
        {suffix ? <span className="muted"> {suffix}</span> : null}
      </span>
    </div>
  );
}

/** What a loan for this place would cost each month, worked out in the browser. */
export function RepaymentCalculator() {
  const [price, setPrice] = useState(750000);
  const [deposit, setDeposit] = useState(20);
  const [rate, setRate] = useState(6);
  const [years, setYears] = useState(30);
  const loan = (price || 0) * (1 - (deposit || 0) / 100);
  const monthly = monthlyRepayment(loan, rate || 0, years || 0);
  return (
    <section className="panel repayment" aria-labelledby="repayment-title">
      <h2 id="repayment-title" className="section-title">
        What would the repayments be?
      </h2>
      <p className="muted">
        Put in the price you&apos;re thinking of, your deposit and a rate. The
        rate here is only an example: a finance specialist can tell you what
        you&apos;d really get.
      </p>
      <div className="repayment-fields">
        <NumberField
          label="Price ($)"
          value={price}
          onChange={setPrice}
          step={10000}
        />
        <NumberField
          label="Deposit"
          value={deposit}
          onChange={setDeposit}
          step={1}
          suffix="%"
        />
        <NumberField
          label="Interest rate"
          value={rate}
          onChange={setRate}
          step={0.05}
          suffix="% a year"
        />
        <NumberField
          label="Loan term"
          value={years}
          onChange={setYears}
          step={1}
          suffix="years"
        />
      </div>
      <p className="repayment-result" role="status">
        <strong>{dollars(monthly)} a month</strong>
        <span className="muted">
          {" "}
          ({dollars((monthly * 12) / 52)} a week) on a loan of {dollars(loan)},
          principal and interest.
        </span>
      </p>
      {deposit < 20 && loan > 0 ? (
        <p className="hint">
          With less than a 20% deposit most lenders add lenders mortgage
          insurance, unless you qualify for a government guarantee scheme.
        </p>
      ) : null}
    </section>
  );
}

function Chart({ chart }: { chart: ReportChart }) {
  // The longest bar fills the row, so small shares stay readable.
  const top = Math.max(
    1,
    ...chart.bars.flatMap((b) => [b.value, b.compare ?? 0]),
  );
  return (
    <figure className="report-chart">
      <figcaption>
        <strong>{chart.title}</strong>
        {chart.compare_label ? (
          <span className="report-chart-key">
            <span className="report-bar-swatch" aria-hidden="true" /> This
            suburb{" "}
            <span className="report-bar-swatch compare" aria-hidden="true" />{" "}
            {chart.compare_label}
          </span>
        ) : null}
      </figcaption>
      <dl>
        {chart.bars.map((b) => (
          <div key={b.label} className="report-bar-row">
            <dt>{b.label}</dt>
            <dd>
              <span className="report-bars" aria-hidden="true">
                <span
                  className="report-bar"
                  style={{ width: `${(b.value * 100) / top}%` }}
                />
                {b.compare != null ? (
                  <span
                    className="report-bar compare"
                    style={{ width: `${(b.compare * 100) / top}%` }}
                  />
                ) : null}
              </span>
              <span className="report-bar-value">
                {b.value}%
                {b.compare != null ? (
                  <span className="muted">
                    {" "}
                    ({chart.compare_label} {b.compare}%)
                  </span>
                ) : null}
              </span>
            </dd>
          </div>
        ))}
      </dl>
    </figure>
  );
}

function Scores({
  scores,
  overall,
}: {
  scores: ReportScore[];
  overall: number | null;
}) {
  if (scores.length === 0) return null;
  return (
    <section className="panel report-scores" aria-labelledby="report-scores">
      <h2 id="report-scores" className="section-title">
        Neighbourhood scores
      </h2>
      {overall != null ? (
        <p className="report-overall">
          <strong>{overall.toFixed(1)}</strong>
          <span className="muted"> out of 10 overall</span>
        </p>
      ) : null}
      <ul className="report-score-list">
        {scores.map((s) => (
          <li key={s.key}>
            <span className="report-score-value">
              {s.score.toFixed(1)}
              <small>/10</small>
            </span>
            <span className="report-score-meter" aria-hidden="true">
              <span style={{ width: `${s.score * 10}%` }} />
            </span>
            <strong>{s.label}</strong>
            <span className="muted">{s.summary}</span>
          </li>
        ))}
      </ul>
      <p className="hint">
        Worked out from the distances in this report, so you can see exactly why
        each score is what it is.
      </p>
    </section>
  );
}

function Section({ section }: { section: ReportSection }) {
  return (
    <section
      className="panel report-section"
      aria-labelledby={`report-${section.key}`}
    >
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
      {(section.charts ?? []).map((c) => (
        <Chart key={c.title} chart={c} />
      ))}
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
                {item.detail ? (
                  <span className="muted"> · {item.detail}</span>
                ) : null}
              </span>
              {item.distance_m != null ? (
                <span className="report-distance">
                  {distanceWords(item.distance_m)}
                </span>
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
        Gathering government, census, school, crime, noise and local data for
        this property…
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
        <p className="hint">
          Free with your account. Every figure says where it comes from.
        </p>
      </section>
      <Scores
        scores={report.scores ?? []}
        overall={report.overall_score ?? null}
      />
      {report.sections.map((s) => (
        <div key={s.key} className="report-block">
          <Section section={s} />
          {s.key === "market" ? (
            <>
              <RepaymentCalculator />
              <FinanceCallout vertical="SELL" />
            </>
          ) : null}
        </div>
      ))}
      <p className="hint">{report.disclaimer}</p>
    </div>
  );
}
