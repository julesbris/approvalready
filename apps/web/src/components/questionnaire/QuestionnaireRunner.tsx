"use client";

import type { PrefillSuggestion, QuestionOut, SubmissionOut } from "@approvalready/shared-types";
import Link from "next/link";
import { useMemo, useState } from "react";

import { FormError } from "@/components/auth/FormStatus";
import { QuestionField } from "@/components/questionnaire/QuestionField";
import { apiRequest } from "@/lib/client-api";
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
};

function without<T>(record: Record<string, T>, key: string): Record<string, T> {
  const copy = { ...record };
  delete copy[key];
  return copy;
}

function initialTexts(submission: SubmissionOut): Record<string, string | undefined> {
  const texts: Record<string, string | undefined> = {};
  for (const question of allQuestions(submission.questionnaire)) {
    texts[question.key] = textFor(question, submission.answers[question.key]);
  }
  return texts;
}

/**
 * Guided questionnaire: one section at a time, with questions appearing and disappearing as
 * answers change, a save per section, then a review step before submitting.
 */
export function QuestionnaireRunner({
  organisationId,
  projectId,
  submission: initial,
  canWrite,
  suggestions: initialSuggestions = [],
}: Props) {
  const [submission, setSubmission] = useState(initial);
  const [draft, setDraft] = useState<Answers>(initial.answers);
  const [texts, setTexts] = useState(() => initialTexts(initial));
  const [textErrors, setTextErrors] = useState<Record<string, string>>({});
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [showTextErrors, setShowTextErrors] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [suggestions, setSuggestions] = useState(initialSuggestions);

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
    setDraft((d) => ({ ...d, [question.key]: value }));
    setFieldErrors((e) => without(e, question.key));
  }

  function setText(question: QuestionOut, text: string) {
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
    const result = await apiRequest<SubmissionOut>("PUT", `${url}/answers`, { answers });
    setBusy(false);
    if (!result.ok) {
      setFieldErrors(result.fields ?? {});
      setError(result.fields ? "Check the highlighted answers." : result.message);
      return false;
    }
    applySaved(result.data);
    return true;
  }

  async function applySuggestions() {
    const answers: Answers = {};
    for (const s of suggestions) answers[s.key] = s.value;
    setBusy(true);
    setError(null);
    setNotice(null);
    const result = await apiRequest<SubmissionOut>("PUT", `${url}/answers`, { answers });
    setBusy(false);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    applySaved(result.data);
    setSuggestions([]);
    setNotice("Filled in from your site details. Check them as you go.");
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
      </nav>

      {editable && suggestions.length > 0 ? (
        <section className="panel" aria-labelledby="prefill-title">
          <h2 id="prefill-title" className="section-title">
            We can fill in {suggestions.length === 1 ? "an answer" : `${suggestions.length} answers`}{" "}
            for you
          </h2>
          <dl className="review-list">
            {suggestions.map((s) => {
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
            <button type="button" className="button" disabled={busy} onClick={applySuggestions}>
              Use these answers
            </button>
            <button
              type="button"
              className="button button-secondary"
              disabled={busy}
              onClick={() => setSuggestions([])}
            >
              No thanks
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
      ) : (
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
              />
            ))}
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
