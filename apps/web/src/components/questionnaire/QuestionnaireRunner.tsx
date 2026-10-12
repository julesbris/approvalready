"use client";

import type {
  AddressMatchOut,
  AnswersResultOut,
  ApprovalGuideOut,
  AssessmentOut,
  CouncilOut,
  PrefillOut,
  PrefillSuggestion,
  QuestionOut,
  SubmissionOut,
} from "@approvalready/shared-types";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { AssessmentReport } from "@/components/assessments/AssessmentReport";
import { FormError } from "@/components/auth/FormStatus";
import { CouncilGuide } from "@/components/councils/CouncilGuide";
import { QuestionField } from "@/components/questionnaire/QuestionField";
import { guideKinds, guideQuery } from "@/lib/approvalGuides";
import { CONFIDENCE_HELP, CONFIDENCE_LABELS, MAP_VERTICALS } from "@/lib/assessment";
import { apiRequest } from "@/lib/client-api";
import { councilKey } from "@/lib/councils";
import {
  type Answers,
  allQuestions,
  cleanAnswer,
  displayAnswer,
  parseText,
  textFor,
  visibility,
} from "@/lib/questionnaire";

type Props = {
  organisationId: string;
  projectId: string;
  submission: SubmissionOut;
  canWrite: boolean;
  /** Answers we can offer from the project's property (and the property facts provider). */
  suggestions?: PrefillSuggestion[];
  /** Wait this long after the last change before saving it automatically. */
  autosaveDelayMs?: number;
  /** The latest assessment of these answers, shown as the result under them. */
  assessment?: AssessmentOut | null;
  /** Step-by-step guides for the approvals that assessment found. */
  guides?: ApprovalGuideOut[];
};

/** The result under the answers, and whether answers changed since it was worked out. */
type Result = { assessment: AssessmentOut; guides: ApprovalGuideOut[]; stale: boolean };

type SaveState = "idle" | "saving" | "saved" | "unsaved";

const COUNCIL_KEY = "property.lga";
const LOT_PLAN_KEY = "property.lot_plan";
const ADDRESS_KEY = "property.address";
/** Answers that change what we can look up about the site. */
const SITE_KEYS = new Set([ADDRESS_KEY, COUNCIL_KEY, LOT_PLAN_KEY]);
/** Optional site facts we look up from the address: asked only once there is one. */
const FROM_ADDRESS = new Set([COUNCIL_KEY, LOT_PLAN_KEY, "property.land_area_m2"]);

/** An answer we filled in for the person, and what it was before, so it can be undone. */
type Filled = { suggestion: PrefillSuggestion; previous: unknown };

/** Facts about the site itself, as opposed to the business or vessel. */
function aboutTheSite(key: string): boolean {
  return key.startsWith("property.") || key === "planning.known_constraints";
}

/**
 * Which suggestions to fill in now. Never one the person declined or changed themselves; and
 * if they chose a different address from the one we'd suggest, nothing else about the site
 * either, because those facts would be about the other address.
 */
function usable(
  list: PrefillSuggestion[],
  skip: Set<string>,
  answers: Answers,
): PrefillSuggestion[] {
  const otherSite = list.some((s) => s.key === ADDRESS_KEY && skip.has(ADDRESS_KEY));
  return list.filter(
    (s) =>
      !skip.has(s.key) &&
      !(otherSite && aboutTheSite(s.key)) &&
      JSON.stringify(answers[s.key]) !== JSON.stringify(s.value),
  );
}

function fill(answers: Answers, list: PrefillSuggestion[]): { answers: Answers; filled: Filled[] } {
  const next = { ...answers };
  const filled: Filled[] = [];
  for (const suggestion of list) {
    filled.push({ suggestion, previous: answers[suggestion.key] });
    next[suggestion.key] = suggestion.value;
  }
  return { answers: next, filled };
}

function without<T>(record: Record<string, T>, key: string): Record<string, T> {
  const copy = { ...record };
  delete copy[key];
  return copy;
}

function initialTexts(
  submission: SubmissionOut,
  answers: Answers = submission.answers,
): Record<string, string | undefined> {
  const texts: Record<string, string | undefined> = {};
  for (const question of allQuestions(submission.questionnaire)) {
    texts[question.key] = textFor(question, answers[question.key]);
  }
  return texts;
}

/**
 * Guided questionnaire: one section at a time, with questions appearing and disappearing as
 * answers change, a progress bar at the top and one main button. The last section's button
 * submits the answers and assesses them in one go, and the result appears right under a
 * summary of the answers, on the same page. Answers save automatically a moment
 * after each change (and again on "Continue"), so people can leave and come back.
 * Picking a Queensland address fills in its postcode, council and lot and plan, and once the
 * site is saved we fill in whatever else we can look up about it (land area, mapped
 * constraints, or the project's saved property), say where each came from, and let the
 * person undo it. For a council in our directory, the result shows how to apply to it.
 * Changing an answer after the result reopens the answers; finishing again updates it.
 */
export function QuestionnaireRunner({
  organisationId,
  projectId,
  submission: initial,
  canWrite,
  suggestions: initialSuggestions = [],
  autosaveDelayMs = 1200,
  assessment: initialAssessment = null,
  guides: initialGuides = [],
}: Props) {
  // What we can look up is filled in straight away (and saved by the autosave below).
  const [start] = useState(() =>
    canWrite && initial.status !== "SUBMITTED"
      ? fill(initial.answers, usable(initialSuggestions, new Set(), initial.answers))
      : { answers: initial.answers, filled: [] },
  );
  const [submission, setSubmission] = useState(initial);
  const [draft, setDraft] = useState<Answers>(start.answers);
  const [texts, setTexts] = useState(() => initialTexts(initial, start.answers));
  const [textErrors, setTextErrors] = useState<Record<string, string>>({});
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [showTextErrors, setShowTextErrors] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [filled, setFilled] = useState<Filled[]>(start.filled);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [council, setCouncil] = useState<CouncilOut | null>(null);
  const [result, setResult] = useState<Result | null>(() =>
    initialAssessment
      ? {
          assessment: initialAssessment,
          guides: initialGuides,
          stale: initial.status !== "SUBMITTED",
        }
      : null,
  );
  // Keys changed since they were last saved, and the save queue (one request at a time).
  const dirty = useRef(new Set(start.filled.map((f) => f.suggestion.key)));
  const queue = useRef<Promise<void>>(Promise.resolve());
  // Answers the person undid or set themselves: we don't fill those in over them.
  const declined = useRef(new Set<string>());
  // The latest answers, for a save that runs after later changes were made.
  const latest = useRef({ draft, textErrors });
  useEffect(() => {
    latest.current = { draft, textErrors };
  }, [draft, textErrors]);

  const questionnaire = submission.questionnaire;
  const sections = questionnaire.sections;
  const submitted = submission.status === "SUBMITTED";
  const editable = canWrite && !submitted;
  const [requestedStep, setStep] = useState(() => (submitted ? sections.length : 0));
  const url = `/organisations/${organisationId}/submissions/${submission.id}`;

  const { visible } = useMemo(() => visibility(questionnaire, draft), [questionnaire, draft]);
  const shownIn = (index: number) =>
    (sections[index]?.questions ?? []).filter((q) => visible.has(q.key));
  // Sections whose questions are all hidden are skipped.
  const steps = sections.map((_, index) => index).filter((index) => shownIn(index).length > 0);
  // If the current section's questions all became hidden, move on to the next one showing.
  const step =
    requestedStep >= sections.length || steps.includes(requestedStep)
      ? requestedStep
      : (steps.find((index) => index > requestedStep) ?? sections.length);

  function setValue(question: QuestionOut, value: unknown) {
    dirty.current.add(question.key);
    declined.current.add(question.key);
    setDraft((d) => ({ ...d, [question.key]: value }));
    setFieldErrors((e) => without(e, question.key));
  }

  // Fill in what we can now look up about the site, and save it.
  const refreshSuggestions = useCallback(async () => {
    const result = await apiRequest<PrefillOut>("GET", `${url}/prefill`);
    if (!result.ok) return;
    const list = usable(result.data.suggestions, declined.current, latest.current.draft);
    if (list.length === 0) return;
    const questions = allQuestions(questionnaire);
    const done = fill(latest.current.draft, list);
    for (const f of done.filled) dirty.current.add(f.suggestion.key);
    setDraft((d) => ({ ...d, ...Object.fromEntries(list.map((s) => [s.key, s.value])) }));
    setTexts((t) => {
      const next = { ...t };
      for (const s of list) {
        const question = questions.find((q) => q.key === s.key);
        if (question) next[s.key] = textFor(question, s.value);
      }
      return next;
    });
    setFilled((before) => [
      ...before.filter((f) => !list.some((s) => s.key === f.suggestion.key)),
      ...done.filled.map((f) => ({
        ...f,
        previous: before.find((b) => b.suggestion.key === f.suggestion.key)?.previous ?? f.previous,
      })),
    ]);
  }, [url, questionnaire]);

  // Save changed answers a moment after the last change. Only answers that parse are sent;
  // the rest wait until they do (or until "Continue" shows what's wrong).
  const autosave = useCallback(() => {
    queue.current = queue.current.then(async () => {
      const questions = allQuestions(questionnaire);
      const { draft: answersNow, textErrors: errorsNow } = latest.current;
      const keys = [...dirty.current].filter((key) => !errorsNow[key]);
      if (keys.length === 0) return;
      const answers: Answers = {};
      for (const key of keys) {
        const question = questions.find((q) => q.key === key);
        if (question) answers[key] = cleanAnswer(question, answersNow[key]);
        dirty.current.delete(key);
      }
      setSaveState("saving");
      const result = await apiRequest<SubmissionOut>("PUT", `${url}/answers`, { answers });
      if (!result.ok) {
        for (const key of keys) dirty.current.add(key);
        setSaveState("unsaved");
        return;
      }
      setSubmission(result.data);
      setSaveState(dirty.current.size > 0 ? "unsaved" : "saved");
      if (keys.some((key) => SITE_KEYS.has(key))) await refreshSuggestions();
    });
  }, [questionnaire, url, refreshSuggestions]);

  // Every change to the answers restarts the wait before saving.
  useEffect(() => {
    if (!editable || dirty.current.size === 0) return;
    const timer = setTimeout(autosave, autosaveDelayMs);
    return () => clearTimeout(timer);
  }, [editable, autosave, autosaveDelayMs, draft]);

  // The council the site is in, from the directory, for "how to apply".
  const chosenCouncil = councilKey(draft[COUNCIL_KEY]);
  useEffect(() => {
    if (!chosenCouncil) return;
    let current = true;
    void apiRequest<CouncilOut>("GET", `/councils/${encodeURIComponent(chosenCouncil)}`).then(
      (result) => {
        if (current) setCouncil(result.ok ? result.data : null);
      },
    );
    return () => {
      current = false;
    };
  }, [chosenCouncil]);
  const shownCouncil = chosenCouncil && council?.key === chosenCouncil ? council : null;

  function onAddressPick(match: AddressMatchOut) {
    const questions = allQuestions(questionnaire);
    const councilQuestion = questions.find((q) => q.key === COUNCIL_KEY);
    const filled: string[] = [];
    const updates: Answers = {};
    if (match.lga && councilQuestion?.options.some((o) => o.value === match.lga)) {
      updates[COUNCIL_KEY] = match.lga;
      filled.push("council");
    }
    if (match.lot_plan_label && questions.some((q) => q.key === LOT_PLAN_KEY)) {
      updates[LOT_PLAN_KEY] = match.lot_plan_label;
      filled.push("lot and plan");
    }
    if (filled.length === 0) return;
    for (const key of Object.keys(updates)) {
      dirty.current.add(key);
      declined.current.add(key); // they're for the address just picked
    }
    setDraft((d) => ({ ...d, ...updates }));
    setFieldErrors((e) => {
      let rest = e;
      for (const key of Object.keys(updates)) rest = without(rest, key);
      return rest;
    });
    setNotice(
      `We filled in the ${match.postcode ? "postcode, " : ""}${filled.join(" and ")} from ` +
        "government address data. Anything else we can look up follows in a moment.",
    );
  }

  function setText(question: QuestionOut, text: string) {
    declined.current.add(question.key);
    setTexts((t) => ({ ...t, [question.key]: text }));
    const parsed = parseText(question, text);
    if ("error" in parsed) {
      setTextErrors((e) => ({ ...e, [question.key]: parsed.error }));
      setDraft((d) => without(d, question.key));
    } else {
      setTextErrors((e) => without(e, question.key));
      setValue(question, parsed.value);
    }
  }

  function applySaved(saved: SubmissionOut) {
    dirty.current.clear();
    setSaveState("saved");
    setSubmission(saved);
    setDraft(saved.answers);
    setTexts(initialTexts(saved));
    setTextErrors({});
    setFieldErrors({});
    setShowTextErrors(false);
    if (saved.pruned.length > 0) {
      setNotice(
        `${saved.pruned.length === 1 ? "One answer no longer applies and was" : `${saved.pruned.length} answers no longer apply and were`} removed.`,
      );
    }
  }

  async function saveSection(index: number): Promise<boolean> {
    const questions = shownIn(index);
    const pending = questions.filter((q) => textErrors[q.key]);
    if (pending.length > 0) {
      setShowTextErrors(true);
      setError("Check the highlighted answers.");
      return false;
    }
    const answers: Answers = {};
    for (const question of questions) answers[question.key] = cleanAnswer(question, draft[question.key]);
    // Answers that became hidden in this section are pruned by the API on save.
    setBusy(true);
    setError(null);
    setNotice(null);
    await queue.current; // let an automatic save in progress finish first
    const result = await apiRequest<SubmissionOut>("PUT", `${url}/answers`, { answers });
    setBusy(false);
    if (!result.ok) {
      setFieldErrors(result.fields ?? {});
      setError(result.fields ? "Check the highlighted answers." : result.message);
      return false;
    }
    applySaved(result.data);
    if (questions.some((q) => SITE_KEYS.has(q.key))) await refreshSuggestions();
    return true;
  }

  function undoFilled() {
    const questions = allQuestions(questionnaire);
    const previous = Object.fromEntries(filled.map((f) => [f.suggestion.key, f.previous]));
    for (const key of Object.keys(previous)) {
      dirty.current.add(key);
      declined.current.add(key);
    }
    setDraft((d) => ({ ...d, ...previous }));
    setTexts((t) => {
      const next = { ...t };
      for (const [key, value] of Object.entries(previous)) {
        const question = questions.find((q) => q.key === key);
        if (question) next[key] = textFor(question, value);
      }
      return next;
    });
    setFilled([]);
    setNotice("We put back the answers you had before.");
  }

  function nextStep(after: number): number {
    return steps.find((index) => index > after) ?? sections.length;
  }

  function previousStep(before: number): number | undefined {
    return [...steps].reverse().find((index) => index < before);
  }

  async function onContinue() {
    if (!(await saveSection(step))) return;
    if (nextStep(step) >= sections.length) {
      await showResult();
      return;
    }
    setStep(nextStep(step));
    window.scrollTo?.({ top: 0 });
  }

  /** Submit the answers (if they aren't already) and assess them, then show the result. */
  async function showResult() {
    setBusy(true);
    setError(null);
    await queue.current; // let an automatic save in progress finish first
    const outcome = await apiRequest<AnswersResultOut>("POST", `${url}/result`);
    if (!outcome.ok) {
      setBusy(false);
      const fields = outcome.fields ?? {};
      setFieldErrors(fields);
      // Take them to the first section with something still to answer.
      const first = steps.find((index) => shownIn(index).some((q) => fields[q.key]));
      if (first !== undefined) {
        setStep(first);
        setError("Answer the highlighted questions to see your result.");
      } else {
        setError(outcome.message);
      }
      return;
    }
    const { submission: saved, assessment } = outcome.data;
    const kinds = guideKinds(assessment);
    const found =
      kinds.length > 0
        ? await apiRequest<ApprovalGuideOut[]>(
            "GET",
            `/guidance/approvals?${guideQuery(kinds, questionnaire.vertical)}`,
          )
        : null;
    setBusy(false);
    applySaved(saved);
    setResult({ assessment, guides: found?.ok ? found.data : [], stale: false });
    setStep(sections.length);
    setNotice(null);
    // Bring the result into view, just under the answers.
    window.setTimeout(() => document.getElementById("result")?.scrollIntoView?.(), 0);
  }

  /** Go back to a section to change it, reopening submitted answers first. */
  async function changeSection(index: number) {
    if (submitted && canWrite) {
      setBusy(true);
      setError(null);
      const reopened = await apiRequest<SubmissionOut>("POST", `${url}/reopen`);
      setBusy(false);
      if (!reopened.ok) {
        setError(reopened.message);
        return;
      }
      applySaved(reopened.data);
      setNotice(null);
      setResult((r) => (r ? { ...r, stale: true } : r));
    }
    setStep(index);
    window.scrollTo?.({ top: 0 });
  }

  const onResult = step >= sections.length;
  const errorFor = (key: string) =>
    fieldErrors[key] ?? (showTextErrors ? textErrors[key] : undefined);
  const missing = new Set(submission.missing_required);
  const { answered } = submission.progress;
  const lastSection = !onResult && nextStep(step) >= sections.length;
  const back = onResult ? undefined : previousStep(step);
  const finishLabel = result ? "Update my result" : "See my result";
  // The result counts as the last step of the progress bar.
  const position = onResult ? steps.length + 1 : steps.indexOf(step) + 1;
  const percent = Math.round(((onResult ? position : position - 1) / (steps.length + 1)) * 100);
  const canChange = editable || (submitted && canWrite);
  // Until there's an address, the facts we'd look up from it would only be guesses.
  const addressAsked = shownIn(step).some((q) => q.key === ADDRESS_KEY);
  const hasAddress = Object.values((draft[ADDRESS_KEY] ?? {}) as object).some(Boolean);
  const waitsForAddress = (q: QuestionOut) =>
    editable &&
    addressAsked &&
    !hasAddress &&
    FROM_ADDRESS.has(q.key) &&
    !q.required &&
    draft[q.key] === undefined;
  const saveText =
    saveState === "saving"
      ? "Saving…"
      : saveState === "saved"
        ? "Saved"
        : saveState === "unsaved"
          ? "Not saved yet"
          : "Saves as you go";

  return (
    <div className="questionnaire flow">
      <header className="flow-head">
        <p className="flow-kicker">{questionnaire.title}</p>
        <div
          className="flow-meter"
          role="progressbar"
          aria-label="Progress"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent}
        >
          <span style={{ width: `${percent}%` }} />
        </div>
        <div className="flow-status">
          <span>
            {onResult ? "Done" : `Step ${position} of ${steps.length}`}
            {!onResult && submission.progress.required_remaining > 0
              ? ` · ${submission.progress.required_remaining} required still to answer`
              : ""}
          </span>
          {editable ? (
            <span className="save-state" role="status">
              {saveText}
            </span>
          ) : null}
        </div>
      </header>

      {editable && !onResult && filled.length > 0 ? (
        <section className="panel flow-filled" aria-labelledby="prefill-title">
          <h2 id="prefill-title" className="section-title">
            We filled in {filled.length === 1 ? "an answer" : `${filled.length} answers`} for you
          </h2>
          <p className="muted">
            Looked up from the sources shown and saved. Check them, and change anything that
            isn&apos;t right.
          </p>
          <dl className="review-list">
            {filled.map(({ suggestion: s }) => {
              const question = allQuestions(questionnaire).find((q) => q.key === s.key);
              return (
                <div key={s.key}>
                  <dt>{s.label}</dt>
                  <dd>
                    {question ? displayAnswer(question, s.value) : String(s.value)}{" "}
                    <span className="muted">
                      · {s.source}
                      {s.is_mock ? " (test data, not real)" : ""}
                    </span>
                  </dd>
                </div>
              );
            })}
          </dl>
          <div className="button-row tight">
            <button
              type="button"
              className="button button-secondary"
              disabled={busy}
              onClick={undoFilled}
            >
              Undo these
            </button>
            <button type="button" className="button-link" onClick={() => setFilled([])}>
              Hide
            </button>
          </div>
        </section>
      ) : null}

      {notice ? (
        <p className="form-notice" role="status">
          {notice}
        </p>
      ) : null}
      <FormError message={error} />

      {onResult ? (
        <>
          <h1 className="page-title flow-title">
            {result && !result.stale ? "Your result" : "Your answers"}
          </h1>
          <section className="panel flow-card flow-answers" aria-label="Your answers">
            <details className="answers-summary" open={!result || result.stale || undefined}>
              <summary>
                Your answers <span className="muted">· {answered} answered</span>
              </summary>
              {steps.map((index) => (
                <div key={index} className="review-section">
                  <div className="review-head">
                    <h3>{sections[index]?.title}</h3>
                    {canChange ? (
                      <button
                        type="button"
                        className="button-link"
                        disabled={busy}
                        onClick={() => void changeSection(index)}
                      >
                        Change
                      </button>
                    ) : null}
                  </div>
                  <dl className="review-list">
                    {shownIn(index).map((question) => (
                      <div
                        key={question.key}
                        className={missing.has(question.key) ? "missing" : undefined}
                      >
                        <dt>{question.label}</dt>
                        <dd>
                          {missing.has(question.key)
                            ? "Required: not answered yet"
                            : displayAnswer(question, submission.answers[question.key])}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </div>
              ))}
            </details>
            {!result || result.stale ? (
              canWrite ? (
                <div className="flow-actions">
                  <button
                    type="button"
                    className="button flow-primary"
                    disabled={busy || missing.size > 0}
                    onClick={() => void showResult()}
                  >
                    {busy ? "Working it out…" : finishLabel}
                  </button>
                </div>
              ) : (
                <p className="muted">No result yet.</p>
              )
            ) : null}
          </section>
        </>
      ) : (
        <section className="panel flow-card" aria-labelledby="section-title">
          {back !== undefined ? (
            <button
              type="button"
              className="button-link flow-back"
              disabled={busy}
              onClick={() => setStep(back)}
            >
              Back
            </button>
          ) : null}
          <h1 id="section-title" className="page-title flow-title">
            {sections[step]?.title}
          </h1>
          <form
            method="post"
            className="form"
            onSubmit={(event) => {
              event.preventDefault();
              void onContinue();
            }}
          >
            {shownIn(step).filter((q) => !waitsForAddress(q)).map((question) => (
              <QuestionField
                key={question.key}
                question={question}
                value={draft[question.key]}
                text={texts[question.key]}
                error={errorFor(question.key)}
                disabled={!editable || busy}
                onValue={(value) => setValue(question, value)}
                onText={(text) => setText(question, text)}
                files={{ organisationId, projectId }}
                onAddressPick={onAddressPick}
              />
            ))}
            {shownCouncil && shownIn(step).some((q) => q.key === COUNCIL_KEY) ? (
              <p className="form-notice council-found">
                Development applications for this site go to {shownCouncil.name}. Your result
                will show you how to apply to them, with their contact details and fees.
              </p>
            ) : null}
            <div className="flow-actions">
              {editable ? (
                <button type="submit" className="button flow-primary" disabled={busy}>
                  {busy
                    ? lastSection
                      ? "Working it out…"
                      : "Saving…"
                    : lastSection
                      ? finishLabel
                      : "Continue"}
                </button>
              ) : (
                <button
                  type="button"
                  className="button flow-primary"
                  onClick={() => setStep(nextStep(step))}
                >
                  {lastSection ? "See the result" : "Next"}
                </button>
              )}
            </div>
          </form>
        </section>
      )}

      {onResult && result ? (
        <div id="result" className="flow-result">
          {result.stale ? (
            <p className="notice">
              Your answers changed since this result. Choose {finishLabel} to work it out again.
            </p>
          ) : null}
          <ResultSummary projectId={projectId} assessment={result.assessment} />
          <AssessmentReport
            embedded
            assessment={result.assessment}
            projectId={projectId}
            approvalMap={MAP_VERTICALS.has(questionnaire.vertical)}
            guides={result.guides}
          >
            {shownCouncil ? <CouncilGuide council={shownCouncil} answers={draft} /> : null}
          </AssessmentReport>
        </div>
      ) : null}
    </div>
  );
}

/** The result in a sentence, how sure we are, and the one next step. */
function ResultSummary({ projectId, assessment }: { projectId: string; assessment: AssessmentOut }) {
  const approvals = assessment.approval_requirements.length;
  const headline =
    assessment.status === "NO_APPLICABLE_RULES"
      ? "We can't assess this one yet"
      : approvals > 0
        ? `${approvals} approval${approvals === 1 ? "" : "s"} found`
        : "No approvals found from your answers";
  return (
    <section className="panel result-summary" aria-labelledby="result-title">
      <div className="finding-head">
        <div>
          <h2 id="result-title" className="section-title">
            {headline}
          </h2>
          <p>
            {assessment.status === "NO_APPLICABLE_RULES"
              ? "We don't have reviewed rules for your situation yet. This doesn't mean no approval is needed."
              : CONFIDENCE_HELP[assessment.overall_confidence]}
          </p>
        </div>
        <span
          className={`status confidence confidence-${assessment.overall_confidence.toLowerCase()}`}
        >
          {CONFIDENCE_LABELS[assessment.overall_confidence]}
        </span>
      </div>
      <div className="flow-actions">
        <Link
          className="button flow-primary"
          href={`/projects/${projectId}/assessments/${assessment.id}`}
        >
          Open your full report
        </Link>
      </div>
      <p className="hint">
        Download it, add your documents, or have a professional check it. The details are below.
      </p>
    </section>
  );
}
