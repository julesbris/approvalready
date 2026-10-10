"use client";

import type {
  Confidence,
  EvaluateOut,
  OutcomeType,
  PublishChecksOut,
  RuleOut,
  RuleVersionContent,
  RuleVersionOut,
  SourceReferenceOut,
} from "@approvalready/shared-types";
import { CONFIDENCE_LEVELS } from "@approvalready/shared-types";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { CONDITION_HELP, PAYLOAD_HELP, parseJson, prettyJson } from "@/components/admin/json";
import { useAction } from "@/components/admin/useAction";
import { FormError, FormNotice } from "@/components/auth/FormStatus";
import {
  CONFIDENCE_LABELS,
  OUTCOME_LABELS,
  OUTCOME_TYPES,
  RESULT_LABELS,
  type TraceNode,
  VERIFICATION_LABELS,
  describeLeaf,
  leaves,
} from "@/lib/assessment";
import { apiRequest } from "@/lib/client-api";
import { formatDateTime } from "@/lib/labels";

type Result = "MATCH" | "NO_MATCH" | "UNKNOWN";
const RESULTS: Result[] = ["MATCH", "NO_MATCH", "UNKNOWN"];
const RELATIONSHIPS = {
  BASIS: "Basis (the rule encodes this)",
  SUPPORTING: "Supporting",
  EXCEPTION: "Exception",
} as const;
type Relationship = keyof typeof RELATIONSHIPS;

const STATUS_LABELS: Record<string, string> = {
  DRAFT: "Draft",
  PUBLISHED: "Published",
  RETIRED: "Retired",
};

type OutcomeRow = { outcome_type: string; title: string; detail: string; payload: string };
type SourceRow = { source_reference_id: string; relationship: Relationship };
type TestRow = { name: string; expected_result: Result; facts: string };

function outcomeRows(version: RuleVersionOut): Record<Result, OutcomeRow> {
  const rows = Object.fromEntries(
    RESULTS.map((r) => [r, { outcome_type: "", title: "", detail: "", payload: "" }]),
  ) as Record<Result, OutcomeRow>;
  for (const o of version.outcomes) {
    rows[o.on_result as Result] = {
      outcome_type: o.outcome_type,
      title: o.title,
      detail: o.detail ?? "",
      payload: prettyJson(o.payload),
    };
  }
  return rows;
}

/** Edit a draft rule version, test it, and publish it once the gate passes. */
export function RuleVersionEditor({
  version,
  rule,
  checks,
  references,
  canPublish,
}: {
  version: RuleVersionOut;
  rule: RuleOut;
  checks: PublishChecksOut;
  references: SourceReferenceOut[];
  canPublish: boolean;
}) {
  const router = useRouter();
  const save = useAction();
  const lifecycle = useAction();
  const tryIt = useAction();
  const editable = version.status === "DRAFT";

  const [condition, setCondition] = useState(prettyJson(version.condition));
  const [effectiveFrom, setEffectiveFrom] = useState(version.effective_from ?? "");
  const [effectiveTo, setEffectiveTo] = useState(version.effective_to ?? "");
  const [maxConfidence, setMaxConfidence] = useState<Confidence>(version.max_confidence);
  const [notes, setNotes] = useState(version.notes ?? "");
  const [outcomes, setOutcomes] = useState(() => outcomeRows(version));
  const [sources, setSources] = useState<SourceRow[]>(() =>
    version.sources.map((s) => ({
      source_reference_id: s.source_reference_id,
      relationship: s.relationship as Relationship,
    })),
  );
  const [tests, setTests] = useState<TestRow[]>(() =>
    version.test_cases.map((t) => ({
      name: t.name,
      expected_result: t.expected_result as Result,
      facts: prettyJson(t.facts),
    })),
  );
  const [saved, setSaved] = useState(false);
  const [tryFacts, setTryFacts] = useState("{}");
  const [tryOn, setTryOn] = useState("");
  const [evaluation, setEvaluation] = useState<EvaluateOut | null>(null);

  const referenceById = new Map(references.map((r) => [r.id, r]));
  const citable = references.filter(
    (r) =>
      r.verification_status !== "SUPERSEDED" &&
      !sources.some((s) => s.source_reference_id === r.id),
  );
  const url = `/admin/rule-versions/${version.id}`;

  function content(): RuleVersionContent | string {
    const parsedCondition = parseJson(condition, "condition");
    if (!parsedCondition.ok) return parsedCondition.message;
    const testCases: RuleVersionContent["test_cases"] = [];
    for (const t of tests) {
      const facts = parseJson(t.facts, `facts for test "${t.name || "unnamed"}"`);
      if (!facts.ok) return facts.message;
      testCases.push({
        name: t.name,
        expected_result: t.expected_result,
        facts: facts.value as Record<string, unknown>,
      });
    }
    const outcomeList: RuleVersionContent["outcomes"] = [];
    for (const r of RESULTS.filter((result) => outcomes[result].outcome_type)) {
      const payload = parseJson(outcomes[r].payload, `details for "${RESULT_LABELS[r]}"`, {
        optional: true,
      });
      if (!payload.ok) return payload.message;
      outcomeList.push({
        on_result: r,
        outcome_type: outcomes[r].outcome_type as OutcomeType,
        title: outcomes[r].title,
        detail: outcomes[r].detail || null,
        payload: payload.value as Record<string, unknown> | null,
      });
    }
    return {
      condition: parsedCondition.value as Record<string, unknown>,
      effective_from: effectiveFrom || null,
      effective_to: effectiveTo || null,
      max_confidence: maxConfidence,
      notes: notes.trim() || null,
      outcomes: outcomeList,
      sources,
      test_cases: testCases,
    };
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaved(false);
    const body = content();
    if (typeof body === "string") return save.setError(body);
    const result = await save.run(() => apiRequest<RuleVersionOut>("PUT", url, body));
    if (result) {
      setSaved(true);
      router.refresh();
    }
  }

  async function evaluate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const facts = parseJson(tryFacts, "facts");
    if (!facts.ok) return tryIt.setError(facts.message);
    const result = await tryIt.run(() =>
      apiRequest<EvaluateOut>("POST", `${url}/evaluate`, {
        facts: facts.value,
        on: tryOn || null,
      }),
    );
    setEvaluation(result);
  }

  async function transition(path: "publish" | "retire") {
    const result = await lifecycle.run(() => apiRequest<RuleVersionOut>("POST", `${url}/${path}`));
    if (result) router.refresh();
  }

  async function newVersion() {
    const result = await lifecycle.run(() =>
      apiRequest<RuleVersionOut>("POST", `/admin/rules/${rule.id}/versions`),
    );
    if (result) router.push(`/admin/rules/versions/${result.id}`);
  }

  async function deleteDraft() {
    const result = await apiRequest<null>("DELETE", url);
    if (result.ok) router.push(`/admin/rules/${version.rule_set_id}`);
    else lifecycle.setError(result.message);
  }

  const hasDraft = rule.versions.some((v) => v.status === "DRAFT");

  return (
    <>
      <section className="page-head">
        <div>
          <p className="breadcrumb">
            <Link href={`/admin/rules/${version.rule_set_id}`}>{version.rule_set_key}</Link>
          </p>
          <h1 className="page-title">
            {version.rule_title} · v{version.version}
          </h1>
          <p className="muted">
            {version.rule_key}
            {version.published_at ? ` · published ${formatDateTime(version.published_at)}` : ""}
            {version.content_hash ? ` · ${version.content_hash.slice(0, 12)}` : ""}
          </p>
        </div>
        <span className="status">{STATUS_LABELS[version.status]}</span>
      </section>

      <section className="panel" aria-labelledby="lifecycle-title">
        <h2 id="lifecycle-title" className="section-title">
          {editable ? "Ready to publish?" : "Versions"}
        </h2>
        <FormError message={lifecycle.error} />
        {editable ? (
          <>
            <ul className="plain-list" aria-label="Publish checks">
              {checks.checks.map((c) => (
                <li key={c.key} className={c.passed ? "check-pass" : "check-fail"}>
                  {c.message}
                </li>
              ))}
            </ul>
            {checks.warnings.length > 0 ? (
              <ul aria-label="Warnings">
                {checks.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            ) : null}
            {checks.test_results.length > 0 ? (
              <ul className="plain-list" aria-label="Test results">
                {checks.test_results.map((t) => (
                  <li key={t.name} className={t.passed ? "check-pass" : "check-fail"}>
                    {t.name}: expected {RESULT_LABELS[t.expected]?.toLowerCase()}, got{" "}
                    {RESULT_LABELS[t.actual]?.toLowerCase()}
                  </li>
                ))}
              </ul>
            ) : null}
            <p className="hint">Checks reflect the last saved draft.</p>
          </>
        ) : null}
        <div className="button-row">
          {editable && canPublish ? (
            <button
              type="button"
              className="button"
              disabled={!checks.ready || lifecycle.busy}
              onClick={() => transition("publish")}
            >
              Publish v{version.version}
            </button>
          ) : null}
          {version.status === "PUBLISHED" && canPublish ? (
            <button
              type="button"
              className="button button-secondary"
              disabled={lifecycle.busy}
              onClick={() => transition("retire")}
            >
              Retire
            </button>
          ) : null}
          {!hasDraft ? (
            <button
              type="button"
              className="button button-secondary"
              disabled={lifecycle.busy}
              onClick={newVersion}
            >
              Start a new version
            </button>
          ) : null}
          {editable && version.version > 1 ? (
            <button type="button" className="button-link" onClick={deleteDraft}>
              Delete this draft
            </button>
          ) : null}
        </div>
        {editable && !canPublish ? (
          <p className="hint">Someone with permission to publish rules must publish it.</p>
        ) : null}
        <ul className="plain-list" aria-label="All versions">
          {rule.versions.map((v) => (
            <li key={v.id}>
              {v.id === version.id ? (
                <strong>v{v.version}</strong>
              ) : (
                <Link href={`/admin/rules/versions/${v.id}`}>v{v.version}</Link>
              )}{" "}
              · {STATUS_LABELS[v.status]}
              {v.effective_from ? ` · from ${v.effective_from}` : ""}
              {v.effective_to ? ` until ${v.effective_to}` : ""}
            </li>
          ))}
        </ul>
      </section>

      <form method="post" className="form form-wide" onSubmit={submit} aria-label="Rule version">
        <fieldset disabled={!editable} className="plain-fieldset">
          <section className="panel" aria-labelledby="condition-title">
            <h2 id="condition-title" className="section-title">
              Condition
            </h2>
            <label>
              Condition (JSON)
              <textarea
                className="code-input"
                rows={10}
                value={condition}
                onChange={(e) => setCondition(e.target.value)}
              />
              <span className="hint">{CONDITION_HELP}</span>
            </label>
            {version.fact_paths.length > 0 ? (
              <p className="muted">Facts used: {version.fact_paths.join(", ")}</p>
            ) : null}
            <div className="field-row">
              <label>
                In force from
                <input
                  type="date"
                  value={effectiveFrom}
                  onChange={(e) => setEffectiveFrom(e.target.value)}
                />
              </label>
              <label>
                Until (optional, exclusive)
                <input
                  type="date"
                  value={effectiveTo}
                  onChange={(e) => setEffectiveTo(e.target.value)}
                />
              </label>
              <label>
                Highest confidence
                <select
                  value={maxConfidence}
                  onChange={(e) => setMaxConfidence(e.target.value as Confidence)}
                >
                  {CONFIDENCE_LEVELS.map((c) => (
                    <option key={c} value={c}>
                      {CONFIDENCE_LABELS[c]}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <label>
              Notes for reviewers (optional)
              <textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
            </label>
          </section>

          <section className="panel" aria-labelledby="outcomes-title">
            <h2 id="outcomes-title" className="section-title">
              What customers see
            </h2>
            {RESULTS.map((r) => (
              <fieldset key={r} className="plain-fieldset">
                <legend className="finding-label">
                  When the rule result is: {RESULT_LABELS[r]}
                </legend>
                <div className="field-row">
                  <label>
                    Outcome
                    <select
                      value={outcomes[r].outcome_type}
                      onChange={(e) =>
                        setOutcomes({
                          ...outcomes,
                          [r]: { ...outcomes[r], outcome_type: e.target.value },
                        })
                      }
                    >
                      <option value="">Nothing shown</option>
                      {OUTCOME_TYPES.map((t) => (
                        <option key={t} value={t}>
                          {OUTCOME_LABELS[t]}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    Title
                    <input
                      value={outcomes[r].title}
                      maxLength={300}
                      onChange={(e) =>
                        setOutcomes({
                          ...outcomes,
                          [r]: { ...outcomes[r], title: e.target.value },
                        })
                      }
                    />
                  </label>
                </div>
                <label>
                  Detail
                  <textarea
                    rows={2}
                    value={outcomes[r].detail}
                    onChange={(e) =>
                      setOutcomes({
                        ...outcomes,
                        [r]: { ...outcomes[r], detail: e.target.value },
                      })
                    }
                  />
                </label>
                <label>
                  Details for requirements and tasks (optional JSON)
                  <textarea
                    rows={3}
                    className="code-input"
                    value={outcomes[r].payload}
                    onChange={(e) =>
                      setOutcomes({
                        ...outcomes,
                        [r]: { ...outcomes[r], payload: e.target.value },
                      })
                    }
                  />
                  <span className="hint">{PAYLOAD_HELP}</span>
                </label>
              </fieldset>
            ))}
          </section>

          <section className="panel" aria-labelledby="sources-title">
            <h2 id="sources-title" className="section-title">
              Sources
            </h2>
            <p className="muted">
              At least one basis source is required. Confidence comes from the state of these
              references on the assessment date.
            </p>
            <ul className="plain-list" aria-label="Linked sources">
              {sources.map((s, i) => {
                const ref = referenceById.get(s.source_reference_id);
                return (
                  <li key={s.source_reference_id} className="field-row">
                    <span>
                      {ref ? ref.citation : s.source_reference_id}{" "}
                      <span className="muted">
                        ({ref ? VERIFICATION_LABELS[ref.verification_status] : "unknown"})
                      </span>
                    </span>
                    <select
                      aria-label="Relationship"
                      value={s.relationship}
                      onChange={(e) =>
                        setSources(
                          sources.map((x, j) =>
                            j === i
                              ? {
                                  ...x,
                                  relationship: e.target.value as Relationship,
                                }
                              : x,
                          ),
                        )
                      }
                    >
                      {Object.entries(RELATIONSHIPS).map(([value, label]) => (
                        <option key={value} value={value}>
                          {label}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      className="button-link"
                      onClick={() => setSources(sources.filter((_, j) => j !== i))}
                    >
                      Remove
                    </button>
                  </li>
                );
              })}
            </ul>
            {editable ? (
              <label>
                Add a source
                <select
                  value=""
                  onChange={(e) =>
                    e.target.value &&
                    setSources([
                      ...sources,
                      {
                        source_reference_id: e.target.value,
                        relationship: "BASIS",
                      },
                    ])
                  }
                >
                  <option value="">Choose a reference…</option>
                  {citable.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.citation} ({VERIFICATION_LABELS[r.verification_status]})
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
          </section>

          <section className="panel" aria-labelledby="tests-title">
            <h2 id="tests-title" className="section-title">
              Test cases
            </h2>
            <p className="muted">
              Each test gives facts and the result you expect. Every test must pass before the
              version can be published.
            </p>
            {tests.map((t, i) => (
              <fieldset key={i} className="plain-fieldset">
                <legend className="finding-label">Test {i + 1}</legend>
                <div className="field-row">
                  <label>
                    Name
                    <input
                      value={t.name}
                      maxLength={300}
                      onChange={(e) =>
                        setTests(
                          tests.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)),
                        )
                      }
                    />
                  </label>
                  <label>
                    Expected result
                    <select
                      value={t.expected_result}
                      onChange={(e) =>
                        setTests(
                          tests.map((x, j) =>
                            j === i
                              ? {
                                  ...x,
                                  expected_result: e.target.value as Result,
                                }
                              : x,
                          ),
                        )
                      }
                    >
                      {RESULTS.map((r) => (
                        <option key={r} value={r}>
                          {RESULT_LABELS[r]}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <label>
                  Facts (JSON)
                  <textarea
                    className="code-input"
                    rows={3}
                    value={t.facts}
                    onChange={(e) =>
                      setTests(tests.map((x, j) => (j === i ? { ...x, facts: e.target.value } : x)))
                    }
                  />
                </label>
                <button
                  type="button"
                  className="button-link"
                  onClick={() => setTests(tests.filter((_, j) => j !== i))}
                >
                  Remove test
                </button>
              </fieldset>
            ))}
            {editable ? (
              <button
                type="button"
                className="button button-secondary"
                onClick={() =>
                  setTests([...tests, { name: "", expected_result: "MATCH", facts: "{}" }])
                }
              >
                Add a test case
              </button>
            ) : null}
          </section>
        </fieldset>
        {editable ? (
          <div className="button-row">
            <FormError message={save.error} />
            {saved ? <FormNotice>Draft saved.</FormNotice> : null}
            <button type="submit" className="button" disabled={save.busy}>
              Save draft
            </button>
          </div>
        ) : null}
      </form>

      <section className="panel" aria-labelledby="try-title">
        <h2 id="try-title" className="section-title">
          Try it
        </h2>
        <p className="muted">Runs the saved version against facts you enter. Nothing is stored.</p>
        <form
          method="post"
          className="form form-wide"
          onSubmit={evaluate}
          aria-label="Try the rule"
        >
          <FormError message={tryIt.error} />
          <label>
            Facts (JSON)
            <textarea
              className="code-input"
              rows={4}
              value={tryFacts}
              onChange={(e) => setTryFacts(e.target.value)}
            />
          </label>
          <label>
            Assessment date (optional, defaults to today)
            <input type="date" value={tryOn} onChange={(e) => setTryOn(e.target.value)} />
          </label>
          <button type="submit" className="button button-secondary" disabled={tryIt.busy}>
            Evaluate
          </button>
        </form>
        {evaluation ? (
          <div className="finding" aria-live="polite">
            <p>
              <strong>{RESULT_LABELS[evaluation.result]}</strong> ·{" "}
              {CONFIDENCE_LABELS[evaluation.confidence]}
              {evaluation.outcome
                ? ` · ${OUTCOME_LABELS[evaluation.outcome.outcome_type]}: ${evaluation.outcome.title}`
                : ""}
            </p>
            <ul className="because">
              {leaves(evaluation.trace as TraceNode).map((leaf, i) => (
                <li key={i}>{describeLeaf(leaf, {})}</li>
              ))}
            </ul>
            {evaluation.confidence_reasons.length > 0 ? (
              <ul>
                {evaluation.confidence_reasons.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}
      </section>
    </>
  );
}
