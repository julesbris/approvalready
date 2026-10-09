"use client";

import type { AIJobOut, CitedPoint } from "@approvalready/shared-types";
import { useState } from "react";

import { FormError } from "@/components/auth/FormStatus";
import { AI_DRAFT_NOTICE, currentJob, waitForJob } from "@/lib/ai";
import { apiRequest } from "@/lib/client-api";
import { formatDateTime } from "@/lib/labels";

type Props = {
  organisationId: string;
  assessmentId: string;
  jobs: AIJobOut[];
  /** Finding id → its title, to link each point back to the finding it explains. */
  findingTitles: Record<string, string>;
  canWrite: boolean;
  mock?: boolean;
  pollMs?: number;
};

function Points({
  title,
  points,
  findingTitles,
}: {
  title: string;
  points: CitedPoint[];
  findingTitles: Record<string, string>;
}) {
  if (points.length === 0) return null;
  return (
    <>
      <p className="finding-label">{title}</p>
      <ul className="ai-points">
        {points.map((p, i) => (
          <li key={i}>
            {p.text}{" "}
            <span className="muted">
              (from{" "}
              {p.finding_ids.map((id, n) => (
                <span key={id}>
                  {n > 0 ? ", " : ""}
                  <a href={`#finding-${id}`}>{findingTitles[id] ?? "a finding"}</a>
                </span>
              ))}
              )
            </span>
          </li>
        ))}
      </ul>
    </>
  );
}

/** An AI-written plain-language explanation of the findings, clearly marked as such. */
export function AIExplanation(props: Props) {
  const { organisationId, assessmentId, findingTitles, canWrite, mock, pollMs } = props;
  const [jobs, setJobs] = useState(props.jobs);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const job = currentJob(jobs, "ASSESSMENT_EXPLANATION");

  async function ask(regenerate: boolean) {
    setWorking(true);
    setError(null);
    const started = await apiRequest<AIJobOut>(
      "POST",
      `/organisations/${organisationId}/assessments/${assessmentId}/ai/explanation`,
      { regenerate },
    );
    if (!started.ok) {
      setWorking(false);
      setError(started.message);
      return;
    }
    setJobs((list) => [started.data, ...list.filter((j) => j.id !== started.data.id)]);
    const done =
      started.data.status === "PENDING"
        ? await waitForJob(organisationId, started.data, pollMs)
        : started;
    setWorking(false);
    if (!done.ok) {
      setError(done.message);
      return;
    }
    setJobs((list) => list.map((j) => (j.id === done.data.id ? done.data : j)));
  }

  const explanation = job?.status === "SUCCEEDED" ? job.explanation : null;
  const pending = working || job?.status === "PENDING";
  return (
    <section className="panel ai-panel" aria-labelledby="ai-explanation-title">
      <h2 id="ai-explanation-title" className="section-title">
        In plain language <span className="ai-tag">AI draft</span>
      </h2>
      <p className="notice">{AI_DRAFT_NOTICE}</p>
      {mock ? <p className="muted">Test mode: this text is canned, not written by a model.</p> : null}
      <FormError message={error} />
      {explanation ? (
        <div>
          <p>{explanation.summary}</p>
          <Points title="What it means" points={explanation.points} findingTitles={findingTitles} />
          <Points title="Next steps" points={explanation.next_steps} findingTitles={findingTitles} />
          <Points
            title="Questions that would firm this up"
            points={explanation.open_questions}
            findingTitles={findingTitles}
          />
          <p className="muted">Written {formatDateTime(job!.created_at)}</p>
        </div>
      ) : job && !pending && job.status !== "SUCCEEDED" ? (
        <p>{job.error ?? "The explanation couldn't be written."}</p>
      ) : null}
      {pending ? <p aria-live="polite">Writing the explanation…</p> : null}
      {canWrite && !pending ? (
        <div className="button-row tight">
          <button type="button" className="button button-secondary" onClick={() => ask(explanation != null)}>
            {explanation ? "Write it again" : "Explain these findings in plain language"}
          </button>
        </div>
      ) : null}
    </section>
  );
}
