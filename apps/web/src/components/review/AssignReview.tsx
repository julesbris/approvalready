"use client";

import type { StaffReviewOut } from "@approvalready/shared-types";
import { type FormEvent, useState } from "react";

import { useAction } from "@/components/admin/useAction";
import { FormError } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";
import { verticalName } from "@/lib/labels";
import { formatDate } from "@/lib/questionnaire";
import { DISCIPLINE_LABELS, REVIEW_STATUS_LABELS, reviewerName } from "@/lib/review";

/** Staff: give a review request to an eligible professional, or take it back. */
export function AssignReview({ initial }: { initial: StaffReviewOut }) {
  const [view, setView] = useState(initial);
  const [professionalId, setProfessionalId] = useState(initial.candidates[0]?.id ?? "");
  const [due, setDue] = useState("");
  const { busy, error, run } = useAction();
  const review = view.review;
  const base = `/admin/reviews/${review.id}`;

  async function assign(event: FormEvent) {
    event.preventDefault();
    const updated = await run(() =>
      apiRequest<StaffReviewOut>("POST", `${base}/assign`, {
        professional_id: professionalId,
        due_on: due || null,
      }),
    );
    if (updated) setView(updated);
  }

  async function unassign() {
    const updated = await run(() => apiRequest<StaffReviewOut>("POST", `${base}/unassign`, {}));
    if (updated) setView(updated);
  }

  return (
    <section className="panel">
      <h1 className="page-title">
        {view.project_title} ({view.project_reference})
      </h1>
      <p>
        <span className="status">{REVIEW_STATUS_LABELS[review.status]}</span>{" "}
        {verticalName(view.vertical)} · requested {formatDate(review.created_at.slice(0, 10))}
      </p>
      {view.rule_sets_in_scope.length > 0 ? (
        <p className="muted">Assessed against: {view.rule_sets_in_scope.join(", ")}.</p>
      ) : null}
      {review.message ? <p className="notice">Customer&apos;s note: {review.message}</p> : null}
      {review.professional ? <p>Assigned to {reviewerName(review.professional)}.</p> : null}
      <FormError message={error} />
      {review.status === "REVIEW_REQUESTED" ? (
        view.candidates.length === 0 ? (
          <p>
            No active professional reviews {verticalName(view.vertical).toLowerCase()} projects
            yet.
          </p>
        ) : (
          <form method="post" className="form" onSubmit={assign}>
            <label>
              Professional
              <select value={professionalId} onChange={(e) => setProfessionalId(e.target.value)}>
                {view.candidates.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.display_name}, {DISCIPLINE_LABELS[c.discipline]} ({c.practice_name})
                  </option>
                ))}
              </select>
            </label>
            <label>
              Due by (optional)
              <input type="date" value={due} onChange={(e) => setDue(e.target.value)} />
            </label>
            <div className="button-row">
              <button type="submit" className="button" disabled={busy || !professionalId}>
                Assign
              </button>
            </div>
          </form>
        )
      ) : null}
      {review.status === "ASSIGNED" ? (
        <button type="button" className="button-link" disabled={busy} onClick={unassign}>
          Take it back (not started yet)
        </button>
      ) : null}
    </section>
  );
}
