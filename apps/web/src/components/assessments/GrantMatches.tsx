import type { GrantMatchOut, MatchStatus } from "@approvalready/shared-types";

import {
  CONFIDENCE_LABELS,
  VERIFICATION_LABELS,
  factLabel,
} from "@/lib/assessment";
import {
  CRITERION_LABELS,
  MATCH_HELP,
  MATCH_LABELS,
  ROUND_LABELS,
  amountRange,
  currentRound,
  roundSummary,
} from "@/lib/grants";

const GROUPS: { status: MatchStatus; title: string }[] = [
  { status: "STRONG_MATCH", title: "Programs you meet the criteria for" },
  { status: "POSSIBLE_MATCH", title: "Programs you might be eligible for" },
  {
    status: "NEEDS_INFORMATION",
    title: "Programs we need more information for",
  },
  { status: "NOT_ELIGIBLE", title: "Programs you don't meet the criteria for" },
];

function Match({
  match,
  labels,
}: {
  match: GrantMatchOut;
  labels: Record<string, string>;
}) {
  const p = match.program;
  const round = currentRound(p);
  const amount = amountRange(p.min_amount_cents, p.max_amount_cents);
  return (
    <li className="finding" id={`grant-${p.id}`}>
      <div className="finding-head">
        <div>
          <h4 className="finding-title">{p.title}</h4>
          <p className="muted">
            {p.administrator.name}
            {amount ? ` · ${amount}` : ""}
          </p>
        </div>
        <span
          className={`status grant-round grant-round-${(round?.state ?? "none").toLowerCase()}`}
        >
          {round ? ROUND_LABELS[round.state] : "No round"}
        </span>
      </div>
      <p>{p.summary}</p>
      {p.funding_summary ? <p className="muted">{p.funding_summary}</p> : null}
      <p>
        <strong>{MATCH_LABELS[match.status]}.</strong>{" "}
        {MATCH_HELP[match.status]}{" "}
        <span className="muted">
          Confidence: {CONFIDENCE_LABELS[match.confidence]}.
        </span>
      </p>
      <p className="finding-label">Criteria we checked</p>
      <ul className="task-list" aria-label={`Criteria for ${p.title}`}>
        {match.criteria.map((c, i) => (
          <li key={c.finding_id ?? `${c.kind}-${i}`} className="task">
            <span>
              {c.title}
              {c.outcome ? <span className="muted"> · {c.outcome}</span> : null}
            </span>
            <span className={`badge criterion-${c.result.toLowerCase()}`}>
              {CRITERION_LABELS[c.result] ?? c.result}
            </span>
          </li>
        ))}
      </ul>
      {match.missing_facts.length > 0 ? (
        <p>
          To finish this check, tell us:{" "}
          {match.missing_facts.map((f) => factLabel(f, labels)).join("; ")}.
        </p>
      ) : null}
      <details>
        <summary>Rounds and dates</summary>
        {p.rounds.length === 0 ? (
          <p className="muted">
            We have no round dates we can cite for this program yet.
          </p>
        ) : (
          <ul className="sources">
            {p.rounds.map((r) => (
              <li key={r.id}>
                <strong>{r.title}</strong>: {roundSummary(r)}
                {r.dates_note ? (
                  <span className="muted"> · {r.dates_note}</span>
                ) : null}
                <br />
                <span className="muted">
                  Source:{" "}
                  <a
                    href={r.source.url}
                    rel="noopener noreferrer"
                    target="_blank"
                  >
                    {r.source.citation}
                  </a>{" "}
                  ·{" "}
                  {VERIFICATION_LABELS[r.source.verification_status] ??
                    r.source.verification_status}
                </span>
              </li>
            ))}
          </ul>
        )}
        <p>
          <a href={p.url} rel="noopener noreferrer" target="_blank">
            Program details from {p.administrator.name}
          </a>
        </p>
      </details>
      {round?.state === "OPEN" && round.closing_soon ? (
        <p className="notice">
          {roundSummary(round)}. Check the program&apos;s guidelines now.
        </p>
      ) : null}
    </li>
  );
}

/** GrantReady: each grant program's match for this assessment, best news first. */
export function GrantMatches({
  matches,
  labels,
}: {
  matches: GrantMatchOut[];
  labels: Record<string, string>;
}) {
  return (
    <section className="panel" aria-labelledby="grants-title">
      <h2 id="grants-title" className="section-title">
        Grant programs
      </h2>
      <p className="hint">
        We check your answers against each program&apos;s published criteria and
        show only dates we can cite. We never estimate your chances: most
        programs are competitive.
      </p>
      {GROUPS.map(({ status, title }) => {
        const list = matches.filter((m) => m.status === status);
        if (list.length === 0) return null;
        return (
          <div key={status}>
            <h3 className="finding-label">
              {title} <span className="muted">({list.length})</span>
            </h3>
            <ul className="finding-list">
              {list.map((m) => (
                <Match key={m.id} match={m} labels={labels} />
              ))}
            </ul>
          </div>
        );
      })}
    </section>
  );
}
