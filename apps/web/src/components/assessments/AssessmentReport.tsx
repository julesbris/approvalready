import type {
  ApprovalMapEntryOut,
  AssessmentOut,
  Certainty,
  FindingOut,
  OverrideOut,
} from "@approvalready/shared-types";
import Link from "next/link";
import type { ReactNode } from "react";

import {
  CERTAINTY_LABELS,
  CONFIDENCE_HELP,
  CONFIDENCE_LABELS,
  OUTCOME_LABELS,
  VERIFICATION_LABELS,
  type TraceNode,
  describeLeaf,
  factLabel,
  groupFindings,
  leaves,
  uniqueSources,
} from "@/lib/assessment";
import { GrantMatches } from "@/components/assessments/GrantMatches";
import { formatDateTime, verticalName } from "@/lib/labels";
import { formatDate } from "@/lib/questionnaire";
import { type ReviewedFinding, applyOverrides } from "@/lib/review";

function ConfidenceBadge({ level }: { level: FindingOut["confidence"] }) {
  return (
    <span className={`status confidence confidence-${level.toLowerCase()}`}>
      {CONFIDENCE_LABELS[level]}
    </span>
  );
}

function ReviewerChange({ finding }: { finding: ReviewedFinding }) {
  const o = finding.override;
  if (!o) return null;
  const was = finding.original;
  return (
    <div className="notice">
      <p>
        <strong>Changed by the professional reviewer.</strong> The assessment said{" "}
        {was.outcome_type ? OUTCOME_LABELS[was.outcome_type] : "no outcome"} (
        {CONFIDENCE_LABELS[was.confidence]}).
      </p>
      <p>{o.reason}</p>
      {o.source ? <p className="muted">Source: {o.source.citation}</p> : null}
    </div>
  );
}

function Finding({
  finding,
  labels,
  actions,
}: {
  finding: ReviewedFinding;
  labels: Record<string, string>;
  actions?: ReactNode;
}) {
  const checks = leaves(finding.trace as TraceNode);
  return (
    <li className="finding" id={`finding-${finding.id}`}>
      <div className="finding-head">
        <div>
          <h3 className="finding-title">{finding.title ?? finding.rule_title}</h3>
          <p className="muted">
            {finding.outcome_type ? `${OUTCOME_LABELS[finding.outcome_type]} · ` : ""}
            {finding.rule_title}
          </p>
        </div>
        <ConfidenceBadge level={finding.confidence} />
      </div>
      {finding.detail ? <p>{finding.detail}</p> : null}
      <ReviewerChange finding={finding} />
      {finding.missing_facts.length > 0 ? (
        <div>
          <p className="finding-label">Information we still need</p>
          <ul>
            {finding.missing_facts.map((fact) => (
              <li key={fact}>{factLabel(fact, labels)}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <details>
        <summary>Why we say this</summary>
        <ul className="because">
          {checks.map((leaf, i) => (
            <li key={i}>{describeLeaf(leaf, labels)}</li>
          ))}
        </ul>
        {finding.confidence_reasons.length > 0 ? (
          <>
            <p className="finding-label">About the confidence</p>
            <ul>
              {finding.confidence_reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          </>
        ) : null}
        <p className="finding-label">Sources</p>
        <ul className="sources">
          {finding.sources.map((s) => (
            <li key={s.reference_id}>
              <a href={s.url} rel="noopener noreferrer" target="_blank">
                {s.citation}
              </a>{" "}
              <span className="muted">
                {s.organisation_name} · {VERIFICATION_LABELS[s.verification_status]}
                {s.in_force ? "" : " · not in force on the assessment date"}
              </span>
            </li>
          ))}
        </ul>
      </details>
      {actions}
    </li>
  );
}

const MAP_COLUMNS: { certainty: Certainty; help: string }[] = [
  { certainty: "REQUIRED", help: "The rules we checked say you need these." },
  { certainty: "LIKELY_REQUIRED", help: "You probably need these." },
  {
    certainty: "MAY_APPLY",
    help: "These depend on details we couldn't check or you haven't told us.",
  },
  {
    certainty: "NOT_IDENTIFIED",
    help: "We checked these and, from your answers, didn't find that they apply.",
  },
];

/** BusinessReady's approval map: every approval checked, once, by how sure we are. */
function ApprovalMap({
  entries,
  changed,
}: {
  entries: ApprovalMapEntryOut[];
  /** Findings a professional reviewer changed. */
  changed: Set<string>;
}) {
  return (
    <div className="approval-map">
      {MAP_COLUMNS.map(({ certainty, help }) => {
        const column = entries.filter((e) => e.certainty === certainty);
        const id = `map-${certainty.toLowerCase()}`;
        return (
          <div key={certainty} className="approval-map-column" aria-labelledby={id}>
            <h3 id={id} className="finding-title">
              {CERTAINTY_LABELS[certainty]} <span className="muted">({column.length})</span>
            </h3>
            <p className="hint">{help}</p>
            {column.length > 0 ? (
              <ul className="finding-list">
                {column.map((e) => (
                  <li key={e.kind} className="finding">
                    <p>
                      <strong>{e.title}</strong>
                    </p>
                    <p className="muted">
                      {e.authority ?? "Authority not stated"} · {CONFIDENCE_LABELS[e.confidence]}
                    </p>
                    {e.pathway ? <p>{e.pathway}</p> : null}
                    {e.finding_ids.some((id) => changed.has(id)) ? (
                      <p className="notice">
                        A professional reviewer changed a finding behind this. See their change
                        below.
                      </p>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">None.</p>
            )}
          </div>
        );
      })}
    </div>
  );
}

function Requirements({
  assessment,
  map,
  changed,
}: {
  assessment: AssessmentOut;
  map: boolean;
  changed: Set<string>;
}) {
  const approvals = assessment.approval_requirements;
  const evidence = assessment.evidence_requirements;
  if (approvals.length === 0 && evidence.length === 0) return null;
  return (
    <section className="panel" aria-labelledby="requirements-title">
      <h2 id="requirements-title" className="section-title">
        {map ? "Your approval map" : "Approvals and what you'll need"}
      </h2>
      {map ? (
        <ApprovalMap entries={assessment.approval_map} changed={changed} />
      ) : approvals.length > 0 ? (
        <ul className="finding-list">
          {approvals.map((a) => (
            <li key={a.id} className="finding">
              <div className="finding-head">
                <div>
                  <h3 className="finding-title">{a.title}</h3>
                  <p className="muted">
                    {CERTAINTY_LABELS[a.certainty]}
                    {a.authority ? ` · ${a.authority}` : ""}
                  </p>
                </div>
                <ConfidenceBadge level={a.confidence} />
              </div>
              {a.pathway ? <p>{a.pathway}</p> : null}
            </li>
          ))}
        </ul>
      ) : null}
      {evidence.length > 0 ? (
        <>
          <p className="finding-label">Things you&apos;ll need to show</p>
          <ul>
            {evidence.map((e) => (
              <li key={e.id}>
                {e.title}
                {e.detail ? <span className="muted"> · {e.detail}</span> : null}
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </section>
  );
}

/** A stored assessment: what applies, what is missing, how sure we are and why. */
export function AssessmentReport({
  assessment,
  projectId,
  overrides,
  findingActions,
  intro,
  approvalMap = false,
  children,
}: {
  assessment: AssessmentOut;
  /** Links back to the customer's project (left out on the reviewer's page). */
  projectId?: string;
  /** Professional reviewers' changes to the findings (shown next to the originals). */
  overrides?: OverrideOut[];
  /** Extra controls under each finding (the reviewer's change form). */
  findingActions?: (finding: FindingOut) => ReactNode;
  /** Shown under the heading (the review panel). */
  intro?: ReactNode;
  /** Show approvals as BusinessReady's map (Required, Likely, May apply, Not identified). */
  approvalMap?: boolean;
  /** Interactive panels (evidence, report downloads) shown after the requirements. */
  children?: ReactNode;
}) {
  const reviewed = applyOverrides(assessment.finding_list, overrides);
  const groups = groupFindings(reviewed);
  const labels = assessment.fact_labels;
  const needsInfo = assessment.rule_sets.filter((rs) => rs.scope === "NEEDS_INFORMATION");
  const sources = uniqueSources(assessment.finding_list);
  return (
    <div className="assessment">
      <section className="page-head" aria-labelledby="assessment-title">
        <div>
          <h1 id="assessment-title" className="page-title">
            Assessment
          </h1>
          <p className="muted">
            As at {formatDate(assessment.assessed_on)} · Run {formatDateTime(assessment.created_at)}
          </p>
        </div>
        <ConfidenceBadge level={assessment.overall_confidence} />
      </section>

      <p className="notice">
        This is general information worked out from your answers and the sources listed, not legal
        or professional advice. Check with the approving authority or a qualified professional
        before you act on it.
      </p>

      {intro}

      {assessment.status === "NO_APPLICABLE_RULES" ? (
        <section className="panel">
          <p>
            We don&apos;t have reviewed rules that cover your situation yet, so we can&apos;t say
            whether approval is needed. This does not mean none is needed.
          </p>
        </section>
      ) : (
        <p>
          <strong>Overall: {CONFIDENCE_LABELS[assessment.overall_confidence]}.</strong>{" "}
          {CONFIDENCE_HELP[assessment.overall_confidence]}
        </p>
      )}

      {assessment.grant_matches && assessment.grant_matches.length > 0 ? (
        <GrantMatches matches={assessment.grant_matches} labels={labels} />
      ) : null}

      <Requirements
        assessment={assessment}
        map={approvalMap}
        changed={new Set(reviewed.filter((f) => f.override).map((f) => f.id))}
      />

      {children}

      {needsInfo.length > 0 ? (
        <section className="panel" aria-labelledby="scope-title">
          <h2 id="scope-title" className="section-title">
            We couldn&apos;t check everything
          </h2>
          {needsInfo.map((rs) => (
            <p key={rs.rule_set_id}>
              {rs.title}: we need{" "}
              {rs.missing_facts.map((f) => factLabel(f, labels)).join(", ") || "more information"}{" "}
              to know whether these rules apply to you.
            </p>
          ))}
        </section>
      ) : null}

      {(
        [
          ["action", "What you may need to do", groups.action],
          ["missing", "What we need to know", groups.missing],
          ["other", "Other findings", groups.other],
        ] as const
      ).map(([key, title, list]) =>
        list.length > 0 ? (
          <section key={key} className="panel" aria-labelledby={`findings-${key}`}>
            <h2 id={`findings-${key}`} className="section-title">
              {title}
            </h2>
            <ul className="finding-list">
              {list.map((f) => (
                <Finding
                  key={f.id}
                  finding={f}
                  labels={labels}
                  actions={findingActions?.(f)}
                />
              ))}
            </ul>
          </section>
        ) : null,
      )}

      {assessment.referral_categories.length > 0 ? (
        <section className="panel" aria-labelledby="help-title">
          <h2 id="help-title" className="section-title">
            Who can help
          </h2>
          <ul>
            {assessment.referral_categories.map((c) => (
              <li key={c.key}>
                {c.label}
                {c.description ? <span className="muted"> · {c.description}</span> : null}
              </li>
            ))}
          </ul>
          <p className="muted">
            These are kinds of professional, not recommendations of particular businesses.
          </p>
        </section>
      ) : null}

      {(assessment.cross_sell ?? []).length > 0 ? (
        <section className="panel" aria-labelledby="cross-sell-title">
          <h2 id="cross-sell-title" className="section-title">
            You might also need
          </h2>
          <ul className="finding-list">
            {(assessment.cross_sell ?? []).map((offer) => (
              <li key={offer.vertical} className="card">
                <p className="card-title">{offer.title}</p>
                {offer.detail ? <p>{offer.detail}</p> : null}
                {projectId ? (
                  <Link
                    className="button button-secondary"
                    href={`/projects/new?vertical=${offer.vertical}`}
                  >
                    Start a {verticalName(offer.vertical)} project
                  </Link>
                ) : (
                  <p className="muted">Suggests {verticalName(offer.vertical)}.</p>
                )}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {sources.length > 0 ? (
        <section className="panel" aria-labelledby="sources-title">
          <h2 id="sources-title" className="section-title">
            Sources
          </h2>
          <ul className="sources">
            {sources.map((s) => (
              <li key={s.reference_id}>
                <a href={s.url} rel="noopener noreferrer" target="_blank">
                  {s.citation}
                </a>{" "}
                <span className="muted">
                  {s.organisation_name} · {VERIFICATION_LABELS[s.verification_status]}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {assessment.limitations.length > 0 ? (
        <section className="panel" aria-labelledby="limitations-title">
          <h2 id="limitations-title" className="section-title">
            What this assessment doesn&apos;t check
          </h2>
          <ul>
            {assessment.limitations.map((text) => (
              <li key={text}>{text}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {projectId && (groups.missing.length > 0 || needsInfo.length > 0) ? (
        <p>
          <Link href={`/projects/${projectId}/questionnaire`}>Update your answers</Link>, submit
          them again and run a new assessment.
        </p>
      ) : null}

      <p className="form-aside">
        Reference for support: assessment {assessment.id.slice(0, 8)} · facts{" "}
        {assessment.facts_hash.slice(0, 12)} · {assessment.engine_version}
      </p>
    </div>
  );
}
