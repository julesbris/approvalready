"use client";

import type { AIJobOut, GrantMatchOut } from "@approvalready/shared-types";
import { useState } from "react";

import { FormError } from "@/components/auth/FormStatus";
import { currentJob, waitForJob } from "@/lib/ai";
import { factLabel } from "@/lib/assessment";
import { apiRequest } from "@/lib/client-api";

type Props = {
  organisationId: string;
  assessmentId: string;
  matches: GrantMatchOut[];
  jobs: AIJobOut[];
  labels: Record<string, string>;
  canWrite: boolean;
  mock?: boolean;
  pollMs?: number;
};

export const GRANT_DRAFT_NOTICE =
  "Written by AI from your own answers and the program's criteria as we recorded them. These " +
  "are notes to start from: check every sentence, add what only you know, and write the " +
  "application in your own words. They say nothing about your chances.";

function Draft({
  job,
  labels,
  criteria,
}: {
  job: AIJobOut;
  labels: Record<string, string>;
  criteria: Record<string, string>;
}) {
  const draft = job.grant_draft;
  if (job.status !== "SUCCEEDED" || !draft) {
    return <p>{job.error ?? "The notes couldn't be written."}</p>;
  }
  return (
    <div className="ai-draft">
      {draft.sections.map((s, i) => (
        <div key={i}>
          <h4 className="subsection-title">{s.heading}</h4>
          <p>{s.text}</p>
          {s.finding_ids.length + s.fact_keys.length > 0 ? (
            <p className="muted">
              Based on:{" "}
              {[
                ...s.finding_ids.map((id) => criteria[id] ?? "a criterion"),
                ...s.fact_keys.map((k) => factLabel(k, labels)),
              ].join("; ")}
            </p>
          ) : null}
        </div>
      ))}
      {draft.missing_information.length > 0 ? (
        <>
          <p className="finding-label">Still to provide or check</p>
          <ul>
            {draft.missing_information.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        </>
      ) : null}
    </div>
  );
}

/** AI-drafted application notes for each grant program the applicant may be eligible for. */
export function GrantDrafts(props: Props) {
  const { organisationId, assessmentId, labels, canWrite, mock, pollMs } = props;
  const [jobs, setJobs] = useState(props.jobs);
  const [working, setWorking] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const matches = props.matches.filter((m) => m.status !== "NOT_ELIGIBLE");
  if (matches.length === 0) return null;

  async function ask(programId: string, regenerate: boolean) {
    setWorking(programId);
    setError(null);
    const started = await apiRequest<AIJobOut>(
      "POST",
      `/organisations/${organisationId}/assessments/${assessmentId}/ai/grant-drafts`,
      { program_id: programId, regenerate },
    );
    if (!started.ok) {
      setWorking(null);
      setError(started.message);
      return;
    }
    setJobs((list) => [started.data, ...list.filter((j) => j.id !== started.data.id)]);
    const done =
      started.data.status === "PENDING"
        ? await waitForJob(organisationId, started.data, pollMs)
        : started;
    setWorking(null);
    if (!done.ok) {
      setError(done.message);
      return;
    }
    setJobs((list) => list.map((j) => (j.id === done.data.id ? done.data : j)));
  }

  return (
    <section className="panel ai-panel" aria-labelledby="grant-drafts-title">
      <h2 id="grant-drafts-title" className="section-title">
        Application notes <span className="ai-tag">AI draft</span>
      </h2>
      <p className="notice">{GRANT_DRAFT_NOTICE}</p>
      {mock ? <p className="muted">Test mode: this text is canned, not written by a model.</p> : null}
      <FormError message={error} />
      {matches.map((m) => {
        const job = currentJob(jobs, "GRANT_DRAFT", m.program.id);
        const pending = working === m.program.id || job?.status === "PENDING";
        const criteria = Object.fromEntries(
          m.criteria.filter((c) => c.finding_id).map((c) => [c.finding_id as string, c.title]),
        );
        const done = job?.status === "SUCCEEDED";
        return (
          <div key={m.program.id} className="report-template">
            <h3 className="subsection-title">{m.program.title}</h3>
            {job && !pending ? <Draft job={job} labels={labels} criteria={criteria} /> : null}
            {pending ? <p aria-live="polite">Writing the notes…</p> : null}
            {canWrite && !pending ? (
              <div className="button-row tight">
                <button
                  type="button"
                  className="button button-secondary"
                  disabled={working !== null}
                  onClick={() => ask(m.program.id, done)}
                >
                  {done ? "Write them again" : "Draft application notes"}
                </button>
              </div>
            ) : null}
          </div>
        );
      })}
    </section>
  );
}
