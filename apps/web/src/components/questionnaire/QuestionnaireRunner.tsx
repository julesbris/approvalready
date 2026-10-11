"use client";

import type {
  AddressMatchOut,
  CouncilOut,
  PrefillOut,
  PrefillSuggestion,
  QuestionOut,
  SubmissionOut,
} from "@approvalready/shared-types";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { FormError } from "@/components/auth/FormStatus";
import { CouncilGuide } from "@/components/councils/CouncilGuide";
import { QuestionField } from "@/components/questionnaire/QuestionField";
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
};

type SaveState = "idle" | "saving" | "saved" | "unsaved";

const COUNCIL_KEY = "property.lga";
const LOT_PLAN_KEY = "property.lot_plan";
const ADDRESS_KEY = "property.address";
/** Answers that change what we can look up about the site. */
const SITE_KEYS = new Set([ADDRESS_KEY, COUNCIL_KEY, LOT_PLAN_KEY]);

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
 * answers change, then a review step before submitting. Answers save automatically a moment
 * after each change (and again on "Save and continue"), so people can leave and come back.
 * Picking a Queensland address fills in its postcode, council and lot and plan, and once the
 * site is saved we fill in whatever else we can look up about it (land area, mapped
 * constraints, or the project's saved property), say where each came from, and let the
 * person undo it. For a council in our directory, the review step shows how to apply to it.
 */
export function QuestionnaireRunner({
  organisationId,
  projectId,
  submission: initial,
  canWrite,
  suggestions: initialSuggestions = [],
  autosaveDelayMs = 1200,
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
  // the rest wait until they do (or until "Save and continue" shows what's wrong).
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
    if (await saveSection(step)) {
      setStep(nextStep(step));
      window.scrollTo?.({ top: 0 });
    }
  }

  async function onSubmit() {
    setBusy(true);
    setError(null);
    const result = await apiRequest<SubmissionOut>("POST", `${url}/submit`);
    setBusy(false);
    if (!result.ok) {
      setFieldErrors(result.fields ?? {});
      setError(result.message);
      return;
    }
    applySaved(result.data);
    setNotice("Your answers are submitted. You can still change them if something was wrong.");
  }

  async function onReopen() {
    setBusy(true);
    setError(null);
    const result = await apiRequest<SubmissionOut>("POST", `${url}/reopen`);
    setBusy(false);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    applySaved(result.data);
    setNotice(null);
    setStep(steps[0] ?? 0);
  }

  const onReview = step >= sections.length;
  const errorFor = (key: string) =>
    fieldErrors[key] ?? (showTextErrors ? textErrors[key] : undefined);
  const missing = new Set(submission.missing_required);
  const { answered, visible: visibleCount } = submission.progress;

  return (
    <div className="questionnaire">
      <header className="page-head">
        <div>
          <h1 className="page-title">{questionnaire.title}</h1>
          {questionnaire.description ? <p className="muted">{questionnaire.description}</p> : null}
        </div>
      </header>

      <nav aria-label="Questionnaire sections">
        <ol className="steps">
          {steps.map((index) => (
            <li key={index} aria-current={index === step ? "step" : undefined}>
              <button type="button" className="button-link" onClick={() => setStep(index)}>
                {sections[index]?.title}
              </button>
            </li>
          ))}
          <li aria-current={onReview ? "step" : undefined}>
            <button type="button" className="button-link" onClick={() => setStep(sections.length)}>
              Review
            </button>
          </li>
        </ol>
        <p className="muted" aria-live="polite">
          {answered} of {visibleCount} questions answered
          {submission.progress.required_remaining > 0
            ? `, ${submission.progress.required_remaining} required still to answer`
            : ""}
          .
        </p>
        {editable ? (
          <p className="muted save-state" role="status">
            {saveState === "saving"
              ? "Saving…"
              : saveState === "saved"
                ? "All changes saved. You can leave and come back to this at any time."
                : saveState === "unsaved"
                  ? "Some answers aren't saved yet. Check them, then choose Save and continue."
                  : "Your answers save as you go."}
          </p>
        ) : null}
      </nav>

      {editable && filled.length > 0 ? (
        <section className="panel" aria-labelledby="prefill-title">
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

      {onReview ? (
        <section className="panel" aria-labelledby="review-title">
          <h2 id="review-title" className="section-title">
            {submitted ? "Your submitted answers" : "Check your answers"}
          </h2>
          {steps.map((index) => (
            <div key={index} className="review-section">
              <div className="review-head">
                <h3>{sections[index]?.title}</h3>
                {editable ? (
                  <button type="button" className="button-link" onClick={() => setStep(index)}>
                    Change
                  </button>
                ) : null}
              </div>
              <dl className="review-list">
                {shownIn(index).map((question) => (
                  <div key={question.key} className={missing.has(question.key) ? "missing" : undefined}>
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
          <p className="muted">
            Submitting records these answers against version {questionnaire.version} of the
            questions. It does not decide anything about approvals.
          </p>
          <div className="button-row">
            {editable ? (
              <button
                type="button"
                className="button"
                disabled={busy || missing.size > 0}
                onClick={onSubmit}
              >
                {busy ? "Submitting…" : "Submit answers"}
              </button>
            ) : null}
            {submitted && canWrite ? (
              <button type="button" className="button button-secondary" disabled={busy} onClick={onReopen}>
                Change answers
              </button>
            ) : null}
            <Link className="button button-secondary" href={`/projects/${projectId}`}>
              Back to project
            </Link>
          </div>
        </section>
      ) : null}
      {onReview && shownCouncil ? <CouncilGuide council={shownCouncil} /> : null}
      {onReview ? null : (
        <section className="panel" aria-labelledby="section-title">
          <h2 id="section-title" className="section-title">
            {sections[step]?.title}
          </h2>
          <form
            method="post"
            className="form"
            onSubmit={(event) => {
              event.preventDefault();
              void onContinue();
            }}
          >
            {shownIn(step).map((question) => (
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
                Development applications for this site go to {shownCouncil.name}. When you
                finish, we&apos;ll show you how to apply to them, with their contact details and
                fees.
              </p>
            ) : null}
            <div className="button-row">
              {editable ? (
                <button type="submit" className="button" disabled={busy}>
                  {busy ? "Saving…" : "Save and continue"}
                </button>
              ) : (
                <button type="button" className="button" onClick={() => setStep(nextStep(step))}>
                  Next
                </button>
              )}
              {previousStep(step) !== undefined ? (
                <button
                  type="button"
                  className="button button-secondary"
                  disabled={busy}
                  onClick={() => setStep(previousStep(step) ?? 0)}
                >
                  Back
                </button>
              ) : null}
            </div>
          </form>
        </section>
      )}
    </div>
  );
}
