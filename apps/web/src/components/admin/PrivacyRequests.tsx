"use client";

import type { PrivacyRequestOut } from "@approvalready/shared-types";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useAction } from "@/components/admin/useAction";
import { FormError } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";
import { formatDateTime } from "@/lib/labels";
import {
  PRIVACY_REQUEST_LABELS,
  PRIVACY_SOURCE_LABELS,
  requestReference,
} from "@/lib/legal";
import { formatDate } from "@/lib/questionnaire";

const STATUS_LABELS: Record<string, string> = {
  OPEN: "Open",
  DONE: "Done",
  DECLINED: "Declined",
};

function RequestItem({ request }: { request: PrivacyRequestOut }) {
  const router = useRouter();
  const { busy, error, run } = useAction();
  const [note, setNote] = useState(request.resolution_note ?? "");
  const overdue = request.overdue;

  async function setStatus(status: "OPEN" | "DONE" | "DECLINED") {
    const saved = await run(() =>
      apiRequest<PrivacyRequestOut>("PATCH", `/admin/privacy/requests/${request.id}`, {
        status,
        note,
      }),
    );
    if (saved) router.refresh();
  }

  return (
    <li className={`privacy-request${overdue ? " privacy-overdue" : ""}`}>
      <div>
        <strong>
          {PRIVACY_REQUEST_LABELS[request.kind] ?? request.kind} · {request.name}
        </strong>{" "}
        <span className="status">{STATUS_LABELS[request.status] ?? request.status}</span>
      </div>
      <div className="muted">
        Ref {requestReference(request.id)} · {PRIVACY_SOURCE_LABELS[request.source]} ·{" "}
        <a href={`mailto:${request.email}`}>{request.email}</a> · received{" "}
        {formatDateTime(request.created_at)} ·{" "}
        {request.status === "OPEN"
          ? `${overdue ? "overdue since" : "answer by"} ${formatDate(request.due_at.slice(0, 10))}`
          : `closed ${request.resolved_at ? formatDateTime(request.resolved_at) : ""}`}
      </div>
      <p className="privacy-request-details">{request.details}</p>
      <form method="post" className="form" onSubmit={(e) => e.preventDefault()}>
        <label>
          Note (what you did, or why not)
          <textarea
            name="note"
            rows={2}
            maxLength={4000}
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </label>
        <FormError message={error} />
        <div className="button-row tight">
          {request.status === "OPEN" ? (
            <>
              <button
                type="button"
                className="button"
                disabled={busy}
                onClick={() => setStatus("DONE")}
              >
                Mark done
              </button>
              <button
                type="button"
                className="button button-secondary"
                disabled={busy}
                onClick={() => setStatus("DECLINED")}
              >
                Decline
              </button>
            </>
          ) : (
            <button
              type="button"
              className="button button-secondary"
              disabled={busy}
              onClick={() => setStatus("OPEN")}
            >
              Reopen
            </button>
          )}
        </div>
      </form>
    </li>
  );
}

/** Staff: privacy requests, open ones first by answer date. */
export function PrivacyRequests({ requests }: { requests: PrivacyRequestOut[] }) {
  if (requests.length === 0) {
    return <p className="muted">No privacy requests yet.</p>;
  }
  return (
    <ul className="task-list" aria-label="Privacy requests">
      {requests.map((r) => (
        <RequestItem key={r.id} request={r} />
      ))}
    </ul>
  );
}
