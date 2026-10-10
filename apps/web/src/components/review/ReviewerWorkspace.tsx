"use client";

import type {
  Confidence,
  Decision,
  EvidenceOut,
  FindingOut,
  FindingSourceOut,
  OutcomeType,
  ReviewerWorkspaceOut,
} from "@approvalready/shared-types";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { useAction } from "@/components/admin/useAction";
import { AssessmentReport } from "@/components/assessments/AssessmentReport";
import { FormError } from "@/components/auth/FormStatus";
import { Conversation, Decisions } from "@/components/review/ReviewPanel";
import {
  CONFIDENCE_LABELS,
  OUTCOME_LABELS,
  VERIFICATION_LABELS,
  uniqueSources,
} from "@/lib/assessment";
import { MAP_VERTICALS } from "@/lib/assessment";
import { type ApiResult, apiRequest } from "@/lib/client-api";
import { formatBytes } from "@/lib/documents";
import { statusLabel, verticalName } from "@/lib/labels";
import { formatDate } from "@/lib/questionnaire";
import { DECISION_LABELS, REVIEW_STATUS_LABELS, reviewDocumentUrl } from "@/lib/review";

type Run = (call: () => Promise<ApiResult<ReviewerWorkspaceOut>>) => Promise<boolean>;

const CONFIDENCES: Confidence[] = ["VERIFIED", "LIKELY", "REVIEW_REQUIRED", "UNKNOWN"];

function OverrideForm({
  finding,
  sources,
  base,
  act,
}: {
  finding: FindingOut;
  sources: FindingSourceOut[];
  base: string;
  act: Run;
}) {
  const [open, setOpen] = useState(false);
  const [outcome, setOutcome] = useState<string>(finding.outcome_type ?? "");
  const [confidence, setConfidence] = useState<Confidence>(finding.confidence);
  const [reason, setReason] = useState("");
  const [sourceId, setSourceId] = useState("");
  if (!open) {
    return (
      <button type="button" className="button-link" onClick={() => setOpen(true)}>
        Change this finding
      </button>
    );
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    const done = await act(() =>
      apiRequest<ReviewerWorkspaceOut>("POST", `${base}/overrides`, {
        finding_id: finding.id,
        new_outcome_type: (outcome || null) as OutcomeType | null,
        new_confidence: confidence,
        reason,
        source_reference_id: sourceId || null,
      }),
    );
    if (done) {
      setOpen(false);
      setReason("");
    }
  }
  return (
    <form
      method="post"
      className="form"
      onSubmit={submit}
      aria-label={`Change ${finding.rule_title}`}
    >
      <label>
        Outcome
        <select value={outcome} onChange={(e) => setOutcome(e.target.value)}>
          <option value="">Keep as is</option>
          {Object.entries(OUTCOME_LABELS).map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <label>
        Confidence
        <select value={confidence} onChange={(e) => setConfidence(e.target.value as Confidence)}>
          {CONFIDENCES.map((c) => (
            <option key={c} value={c}>
              {CONFIDENCE_LABELS[c]}
            </option>
          ))}
        </select>
      </label>
      <label>
        Reason (the customer sees this)
        <textarea
          value={reason}
          minLength={10}
          maxLength={2000}
          rows={3}
          onChange={(e) => setReason(e.target.value)}
          required
        />
      </label>
      <label>
        Source (needed for Verified, which takes a source our team has verified)
        <select value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
          <option value="">None</option>
          {sources.map((s) => (
            <option key={s.reference_id} value={s.reference_id}>
              {s.citation} ({VERIFICATION_LABELS[s.verification_status]})
            </option>
          ))}
        </select>
      </label>
      <div className="button-row">
        <button type="submit" className="button-secondary">
          Save change
        </button>
        <button type="button" className="button-link" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function EvidenceRow({
  item,
  reviewId,
  base,
  act,
  canAct,
}: {
  item: EvidenceOut;
  reviewId: string;
  base: string;
  act: Run;
  canAct: boolean;
}) {
  const [note, setNote] = useState(item.review_note ?? "");
  const decide = (status: "ACCEPTED" | "REJECTED") =>
    act(() =>
      apiRequest<ReviewerWorkspaceOut>("POST", `${base}/evidence/${item.id}`, {
        status,
        note: note.trim() || null,
      }),
    );
  return (
    <li className="task">
      <a href={reviewDocumentUrl(reviewId, item.document.id)} download={item.document.filename}>
        {item.document.filename}
      </a>
      <span className="badge">{item.status.toLowerCase()}</span>
      {item.note ? <span className="muted">Customer: {item.note}</span> : null}
      {canAct ? (
        <span className="inline-form">
          <input
            aria-label={`Note about ${item.document.filename}`}
            placeholder="Note (needed to reject)"
            value={note}
            maxLength={500}
            onChange={(e) => setNote(e.target.value)}
          />
          <button type="button" className="button-link" onClick={() => decide("ACCEPTED")}>
            Accept
          </button>
          <button type="button" className="button-link" onClick={() => decide("REJECTED")}>
            Reject
          </button>
        </span>
      ) : item.review_note ? (
        <span className="muted">Your note: {item.review_note}</span>
      ) : null}
    </li>
  );
}

/** The assigned reviewer's page: the assessment with change controls, files, messages,
 * tasks and the decision. */
export function ReviewerWorkspace({ initial }: { initial: ReviewerWorkspaceOut }) {
  const router = useRouter();
  const [ws, setWs] = useState(initial);
  const [decision, setDecision] = useState<Decision>("APPROVED");
  const [notes, setNotes] = useState("");
  const [task, setTask] = useState("");
  const { busy, error, run } = useAction();
  const review = ws.review;
  const base = `/professional/reviews/${review.id}`;
  const inReview = review.status === "IN_REVIEW";
  const active = ["ASSIGNED", "IN_REVIEW", "CHANGES_REQUIRED"].includes(review.status);
  const sources = uniqueSources(ws.assessment.finding_list);

  const act: Run = async (call) => {
    const data = await run(call);
    if (!data) return false;
    setWs(data);
    return true;
  };

  async function decline() {
    const reason = window.prompt("Why can't you take this review? (optional)") ?? "";
    const done = await run(() =>
      apiRequest("POST", `${base}/decline`, { reason: reason.trim() || null }),
    );
    if (done) router.push("/review");
  }

  async function decide(event: FormEvent) {
    event.preventDefault();
    await act(() =>
      apiRequest<ReviewerWorkspaceOut>("POST", `${base}/decision`, {
        decision,
        notes: notes.trim() || null,
      }),
    );
  }

  async function addTask(event: FormEvent) {
    event.preventDefault();
    const call = () => apiRequest<ReviewerWorkspaceOut>("POST", `${base}/tasks`, { title: task });
    if (await act(call)) setTask("");
  }

  return (
    <div>
      <section className="page-head">
        <div>
          <h1 className="page-title">
            {review.project_title} ({review.project_reference})
          </h1>
          <p className="muted">
            {verticalName(review.vertical)} · project {statusLabel(ws.project_status).toLowerCase()}
            {review.due_on ? ` · due ${formatDate(review.due_on)}` : ""}
          </p>
        </div>
        <span className={`status status-${review.status.toLowerCase()}`}>
          {REVIEW_STATUS_LABELS[review.status]}
        </span>
      </section>
      <FormError message={error} />
      {review.message ? (
        <p className="notice">
          <strong>The customer asked:</strong> {review.message}
        </p>
      ) : null}
      {review.status === "ASSIGNED" ? (
        <div className="button-row">
          <button
            type="button"
            className="button"
            disabled={busy}
            onClick={() => act(() => apiRequest<ReviewerWorkspaceOut>("POST", `${base}/start`))}
          >
            Start the review
          </button>
          <button type="button" className="button-link" disabled={busy} onClick={decline}>
            Decline
          </button>
        </div>
      ) : null}
      {review.status === "CHANGES_REQUIRED" ? (
        <p className="muted">Waiting for the customer to make the changes you asked for.</p>
      ) : null}

      <section className="panel" aria-labelledby="files-title">
        <h2 id="files-title" className="section-title">
          Files
        </h2>
        {ws.shared_documents.length === 0 && ws.evidence.length === 0 ? (
          <p className="muted">The customer hasn&apos;t shared any files.</p>
        ) : null}
        <ul className="task-list" aria-label="Shared files">
          {ws.shared_documents.map((d) => (
            <li key={d.id} className="task">
              {d.scan_status === "CLEAN" ? (
                <a href={reviewDocumentUrl(review.id, d.id)} download={d.filename}>
                  {d.filename}
                </a>
              ) : (
                <span>{d.filename}</span>
              )}
              <span className="muted">{formatBytes(d.size_bytes)}</span>
            </li>
          ))}
        </ul>
        {ws.evidence.length > 0 ? (
          <>
            <h3 className="finding-label">Evidence offered</h3>
            {ws.assessment.evidence_requirements.map((req) => (
              <div key={req.id}>
                <p>
                  <strong>{req.title}</strong>
                </p>
                <ul className="task-list">
                  {ws.evidence
                    .filter((e) => e.evidence_requirement_id === req.id)
                    .map((e) => (
                      <EvidenceRow
                        key={e.id}
                        item={e}
                        reviewId={review.id}
                        base={base}
                        act={act}
                        canAct={inReview}
                      />
                    ))}
                </ul>
              </div>
            ))}
          </>
        ) : null}
      </section>

      <AssessmentReport
        assessment={ws.assessment}
        overrides={review.overrides}
        approvalMap={MAP_VERTICALS.has(review.vertical)}
        findingActions={
          inReview
            ? (f) => <OverrideForm finding={f} sources={sources} base={base} act={act} />
            : undefined
        }
      >
        <section className="panel" aria-labelledby="conversation-title">
          <h2 id="conversation-title" className="section-title">
            Review
          </h2>
          <Decisions review={review} />
          <Conversation
            review={review}
            busy={busy}
            canWrite={active}
            who="reviewer"
            onSend={(body) =>
              act(() => apiRequest<ReviewerWorkspaceOut>("POST", `${base}/comments`, { body }))
            }
          />
          {ws.tasks.length > 0 ? (
            <>
              <h3 className="finding-label">Tasks you added</h3>
              <ul>
                {ws.tasks.map((t) => (
                  <li key={t.id}>
                    {t.title} <span className="muted">({t.status.toLowerCase()})</span>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
          {active ? (
            <form method="post" className="form inline-form" onSubmit={addTask}>
              <label>
                Add a task to the customer&apos;s project
                <input
                  value={task}
                  maxLength={200}
                  onChange={(e) => setTask(e.target.value)}
                  required
                />
              </label>
              <button type="submit" className="button-secondary" disabled={busy}>
                Add task
              </button>
            </form>
          ) : null}
          {inReview ? (
            <form method="post" className="form" onSubmit={decide} aria-label="Decision">
              <fieldset>
                <legend>Your decision</legend>
                {(Object.keys(DECISION_LABELS) as Decision[]).map((d) => (
                  <label key={d}>
                    <input
                      type="radio"
                      name="decision"
                      value={d}
                      checked={decision === d}
                      onChange={() => setDecision(d)}
                    />{" "}
                    {DECISION_LABELS[d]}
                  </label>
                ))}
              </fieldset>
              <label>
                Notes for the customer{decision === "APPROVED" ? " (optional)" : ""}
                <textarea
                  value={notes}
                  maxLength={4000}
                  rows={4}
                  onChange={(e) => setNotes(e.target.value)}
                  required={decision !== "APPROVED"}
                />
              </label>
              <div className="button-row">
                <button type="submit" className="button" disabled={busy}>
                  Send decision
                </button>
              </div>
            </form>
          ) : null}
        </section>
      </AssessmentReport>
    </div>
  );
}
