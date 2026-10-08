import type { AssessmentOut, FindingOut } from "@approvalready/shared-types";
import Link from "next/link";

import {
  CONFIDENCE_HELP,
  CONFIDENCE_LABELS,
  OUTCOME_LABELS,
  VERIFICATION_LABELS,
  type TraceNode,
  describeLeaf,
  factLabel,
  groupFindings,
  leaves,
} from "@/lib/assessment";
import { formatDateTime } from "@/lib/labels";
import { formatDate } from "@/lib/questionnaire";

function ConfidenceBadge({ level }: { level: FindingOut["confidence"] }) {
  return (
    <span className={`status confidence confidence-${level.toLowerCase()}`}>
      {CONFIDENCE_LABELS[level]}
    </span>
  );
}

function Finding({ finding, labels }: { finding: FindingOut; labels: Record<string, string> }) {
  const checks = leaves(finding.trace as TraceNode);
  return (
    <li className="finding">
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
    </li>
  );
}

/** A stored assessment: what applies, what is missing, how sure we are and why. */
export function AssessmentReport({
  assessment,
  projectId,
}: {
  assessment: AssessmentOut;
  projectId: string;
}) {
  const groups = groupFindings(assessment.finding_list);
  const labels = assessment.fact_labels;
  const needsInfo = assessment.rule_sets.filter((rs) => rs.scope === "NEEDS_INFORMATION");
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
                <Finding key={f.id} finding={f} labels={labels} />
              ))}
            </ul>
          </section>
        ) : null,
      )}

      {groups.missing.length > 0 || needsInfo.length > 0 ? (
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
