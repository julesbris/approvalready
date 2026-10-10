"use client";

import type {
  ReviewEventOut,
  SnapshotCaptured,
  SnapshotSummary,
  SourceDocumentOut,
  SourceReferenceOut,
} from "@approvalready/shared-types";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { SOURCE_TYPES } from "@/components/admin/SourceForms";
import { useAction } from "@/components/admin/useAction";
import { FormError, FormNotice } from "@/components/auth/FormStatus";
import { VERIFICATION_LABELS } from "@/lib/assessment";
import { apiRequest } from "@/lib/client-api";
import { formatDateTime } from "@/lib/labels";
import { formatDate } from "@/lib/questionnaire";

const ACTION_LABELS: Record<string, string> = {
  VERIFY: "Verify against the latest snapshot",
  DISPUTE: "Dispute",
  SUPERSEDE: "Mark superseded",
  REOPEN: "Reopen",
};

const EVENT_LABELS: Record<string, string> = {
  CREATED: "Added",
  EDITED: "Edited",
  VERIFIED: "Verified",
  DISPUTED: "Disputed",
  SUPERSEDED: "Superseded",
  REOPENED: "Reopened",
};

function text(form: FormData, name: string): string | null {
  const value = String(form.get(name) ?? "").trim();
  return value === "" ? null : value;
}

function referenceBody(form: FormData) {
  return {
    section: text(form, "section"),
    clause: text(form, "clause"),
    page: text(form, "page"),
    extracted_text: text(form, "extracted_text"),
    interpretation: text(form, "interpretation"),
  };
}

function ReferenceFields({ reference }: { reference?: SourceReferenceOut }) {
  return (
    <>
      <div className="field-row">
        <label>
          Section
          <input name="section" maxLength={100} defaultValue={reference?.section ?? ""} />
        </label>
        <label>
          Clause
          <input name="clause" maxLength={100} defaultValue={reference?.clause ?? ""} />
        </label>
        <label>
          Page
          <input name="page" maxLength={20} defaultValue={reference?.page ?? ""} />
        </label>
      </div>
      <label>
        Exact text from the source
        <textarea
          name="extracted_text"
          required
          rows={4}
          maxLength={10000}
          defaultValue={reference?.extracted_text ?? ""}
        />
      </label>
      <label>
        How we read it (optional)
        <textarea
          name="interpretation"
          rows={2}
          maxLength={10000}
          defaultValue={reference?.interpretation ?? ""}
        />
      </label>
    </>
  );
}

function Reference({
  reference,
  canVerify,
}: {
  reference: SourceReferenceOut;
  canVerify: boolean;
}) {
  const router = useRouter();
  const action = useAction();
  const [editing, setEditing] = useState(false);
  const [events, setEvents] = useState<ReviewEventOut[] | null>(null);
  const url = `/admin/source-references/${reference.id}`;

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const saved = await action.run(() =>
      apiRequest<SourceReferenceOut>(
        "PATCH",
        url,
        referenceBody(new FormData(event.currentTarget)),
      ),
    );
    if (saved) {
      setEditing(false);
      router.refresh();
    }
  }

  async function review(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const submitter = (event.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null;
    const form = new FormData(event.currentTarget);
    const reviewed = await action.run(() =>
      apiRequest<SourceReferenceOut>("POST", `${url}/review`, {
        action: submitter?.value,
        notes: text(form, "notes"),
        next_review_due: text(form, "next_review_due"),
      }),
    );
    if (reviewed) {
      setEvents(null);
      router.refresh();
    }
  }

  async function history() {
    const loaded = await action.run(() => apiRequest<ReviewEventOut[]>("GET", `${url}/events`));
    if (loaded) setEvents(loaded);
  }

  return (
    <li className="finding" id={`ref-${reference.id}`}>
      <div className="finding-head">
        <h3 className="finding-title">{reference.citation}</h3>
        <span className="status">{VERIFICATION_LABELS[reference.verification_status]}</span>
      </div>
      <FormError message={action.error} />
      {reference.attention.length > 0 ? (
        <p className="notice">{reference.attention.join(" ")}</p>
      ) : null}
      {editing ? (
        <form method="post" className="form" onSubmit={save} aria-label="Edit reference">
          <ReferenceFields reference={reference} />
          <p className="hint">Saving a change sets the reference back to not verified.</p>
          <div className="button-row">
            <button type="submit" className="button" disabled={action.busy}>
              Save
            </button>
            <button
              type="button"
              className="button button-secondary"
              onClick={() => setEditing(false)}
            >
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <>
          <blockquote className="extract">{reference.extracted_text}</blockquote>
          {reference.interpretation ? (
            <p>
              <span className="finding-label">How we read it: </span>
              {reference.interpretation}
            </p>
          ) : null}
          <p className="muted">
            {reference.verified_at ? `Verified ${formatDateTime(reference.verified_at)}. ` : ""}
            {reference.next_review_due
              ? `Review due ${formatDate(reference.next_review_due)}. `
              : ""}
            Cited by {reference.rule_versions} rule version(s).
          </p>
        </>
      )}
      {!editing && reference.verification_status !== "SUPERSEDED" ? (
        <div className="button-row">
          <button
            type="button"
            className="button button-secondary"
            onClick={() => setEditing(true)}
          >
            Edit
          </button>
          <button type="button" className="button-link" onClick={history} disabled={action.busy}>
            Show history
          </button>
        </div>
      ) : null}
      {canVerify && !editing && reference.allowed_actions.length > 0 ? (
        <details>
          <summary>Review</summary>
          <form method="post" className="form" onSubmit={review} aria-label="Review reference">
            <label>
              Notes (needed to dispute or supersede)
              <textarea name="notes" rows={2} maxLength={2000} />
            </label>
            <label>
              Next review due (optional, defaults to a year from now)
              <input name="next_review_due" type="date" />
            </label>
            <div className="button-row">
              {reference.allowed_actions.map((a) => (
                <button
                  key={a}
                  type="submit"
                  name="action"
                  value={a}
                  className={a === "VERIFY" ? "button" : "button button-secondary"}
                  disabled={action.busy}
                >
                  {ACTION_LABELS[a]}
                </button>
              ))}
            </div>
          </form>
        </details>
      ) : null}
      {events ? (
        <ol className="history" aria-label="Review history">
          {events.map((e) => (
            <li key={e.id}>
              {EVENT_LABELS[e.action]} by {e.reviewer_name ?? "unknown"},{" "}
              {formatDateTime(e.occurred_at)}
              {e.notes ? `: ${e.notes}` : ""}
            </li>
          ))}
        </ol>
      ) : null}
    </li>
  );
}

/** One source document: provenance, captured snapshots and the references cited by rules. */
export function DocumentWorkspace({
  document,
  snapshots,
  references,
  canVerify,
}: {
  document: SourceDocumentOut;
  snapshots: SnapshotSummary[];
  references: SourceReferenceOut[];
  canVerify: boolean;
}) {
  const router = useRouter();
  const capture = useAction();
  const add = useAction();
  const [captured, setCaptured] = useState<string | null>(null);

  async function captureSnapshot(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const element = event.currentTarget;
    const form = new FormData(element);
    const retrieved = text(form, "retrieved_at");
    const result = await capture.run(() =>
      apiRequest<SnapshotCaptured>("POST", `/admin/source-documents/${document.id}/snapshots`, {
        content_text: String(form.get("content_text") ?? ""),
        retrieved_at: retrieved ? new Date(retrieved).toISOString() : null,
      }),
    );
    if (result) {
      element.reset();
      setCaptured(
        result.changed
          ? "Snapshot saved. Verified references now need checking against it."
          : "The text is the same as the latest snapshot, so nothing changed.",
      );
      router.refresh();
    }
  }

  async function addReference(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const element = event.currentTarget;
    const created = await add.run(() =>
      apiRequest<SourceReferenceOut>(
        "POST",
        `/admin/source-documents/${document.id}/references`,
        referenceBody(new FormData(element)),
      ),
    );
    if (created) {
      element.reset();
      router.refresh();
    }
  }

  return (
    <>
      <section className="page-head">
        <div>
          <h1 className="page-title">{document.title}</h1>
          <p className="muted">
            {document.organisation_name} · {SOURCE_TYPES[document.source_type]} ·{" "}
            {document.jurisdiction}
            {document.version_label ? ` · ${document.version_label}` : ""}
          </p>
        </div>
      </section>
      <section className="panel">
        <dl className="facts">
          <dt>Official address</dt>
          <dd>
            <a href={document.url} rel="noopener noreferrer" target="_blank">
              {document.url}
            </a>
          </dd>
          <dt>In force</dt>
          <dd>
            {document.effective_from
              ? `from ${formatDate(document.effective_from)}`
              : "no start date"}
            {document.effective_to ? `, until ${formatDate(document.effective_to)}` : ""}
          </dd>
          {document.licence ? (
            <>
              <dt>Licence</dt>
              <dd>{document.licence}</dd>
            </>
          ) : null}
        </dl>
      </section>

      <section className="panel" aria-labelledby="snapshots-title">
        <h2 id="snapshots-title" className="section-title">
          Snapshots
        </h2>
        <p className="muted">
          Paste the document&apos;s text as you retrieved it. References are verified against the
          latest snapshot, and a changed snapshot flags them for review.
        </p>
        {snapshots.length > 0 ? (
          <ul aria-label="Snapshots">
            {snapshots.map((s) => (
              <li key={s.id}>
                Retrieved {formatDateTime(s.retrieved_at)} · {s.characters.toLocaleString()}{" "}
                characters · <code>{s.content_hash.slice(0, 12)}</code>
              </li>
            ))}
          </ul>
        ) : (
          <p>No snapshot yet.</p>
        )}
        {captured ? <FormNotice>{captured}</FormNotice> : null}
        <form
          method="post"
          className="form"
          onSubmit={captureSnapshot}
          aria-label="Capture a snapshot"
        >
          <FormError message={capture.error} />
          <label>
            Document text
            <textarea name="content_text" required rows={6} maxLength={1000000} />
          </label>
          <label>
            Retrieved at (optional, defaults to now)
            <input name="retrieved_at" type="datetime-local" />
          </label>
          <button type="submit" className="button button-secondary" disabled={capture.busy}>
            Save snapshot
          </button>
        </form>
      </section>

      <section className="panel" aria-labelledby="refs-title">
        <h2 id="refs-title" className="section-title">
          References
        </h2>
        {references.length > 0 ? (
          <ul className="finding-list" aria-label="References">
            {references.map((r) => (
              <Reference key={`${r.id}-${r.updated_at}`} reference={r} canVerify={canVerify} />
            ))}
          </ul>
        ) : (
          <p>No references yet.</p>
        )}
        <h3 className="section-title">Add a reference</h3>
        <form method="post" className="form" onSubmit={addReference} aria-label="Add a reference">
          <FormError message={add.error} />
          <ReferenceFields />
          <button type="submit" className="button" disabled={add.busy}>
            Add reference
          </button>
        </form>
      </section>
    </>
  );
}
