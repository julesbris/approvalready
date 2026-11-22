"use client";

import type { AccountActionOut, StaffNoteOut } from "@approvalready/shared-types";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { useAction } from "@/components/admin/useAction";
import { FormError, FormNotice } from "@/components/auth/FormStatus";
import { NOTE_KIND_LABELS } from "@/lib/accounts";
import { apiRequest } from "@/lib/client-api";
import { formatDateTime } from "@/lib/labels";

type Draft = { subject: string; message: string };

/** Staff: email this person from the team address (a copy is kept as a note). */
export function EmailCustomer({
  accountId,
  email,
  project,
  draft,
}: {
  accountId: string;
  email: string;
  project: string | null;
  draft: Draft | null;
}) {
  const router = useRouter();
  const { busy, error, fields, run } = useAction();
  const [subject, setSubject] = useState(draft?.subject ?? "");
  const [message, setMessage] = useState(draft?.message ?? "");
  const [reference, setReference] = useState(project ?? "");
  const [done, setDone] = useState<string | null>(null);

  async function send(e: FormEvent) {
    e.preventDefault();
    if (!window.confirm(`Send this email to ${email}?`)) return;
    setDone(null);
    const result = await run(() =>
      apiRequest<AccountActionOut>("POST", `/admin/accounts/${accountId}/email`, {
        subject,
        message,
        project_reference: reference || null,
      }),
    );
    if (result) {
      setDone(result.message);
      setSubject("");
      setMessage("");
      router.refresh();
    }
  }

  return (
    <form method="post" className="form" onSubmit={(e) => void send(e)}>
      {done ? <FormNotice>{done}</FormNotice> : null}
      <p className="hint">
        Goes to {email} from the team address, so replies land in the team inbox. It starts
        with &ldquo;Hi&rdquo; and their name and ends with your first name.
      </p>
      <label>
        Subject
        <input
          name="subject"
          required
          maxLength={200}
          value={subject}
          aria-invalid={fields.subject ? true : undefined}
          onChange={(e) => setSubject(e.target.value)}
        />
      </label>
      <label>
        Message
        <textarea
          name="message"
          required
          rows={6}
          maxLength={8000}
          value={message}
          aria-invalid={fields.message ? true : undefined}
          onChange={(e) => setMessage(e.target.value)}
        />
      </label>
      <label>
        Project (optional)
        <input
          name="project_reference"
          maxLength={40}
          placeholder="For example PLN-ABC123"
          value={reference}
          onChange={(e) => setReference(e.target.value)}
        />
      </label>
      <FormError message={error} />
      <button type="submit" className="button" disabled={busy}>
        {busy ? "Sending…" : "Send email"}
      </button>
    </form>
  );
}

/** Staff: notes and logged calls on this account, and everything emailed from here. */
export function StaffNotes({
  accountId,
  notes,
  canAdd,
  project,
}: {
  accountId: string;
  notes: StaffNoteOut[];
  canAdd: boolean;
  project: string | null;
}) {
  const router = useRouter();
  const { busy, error, fields, run } = useAction();
  const [kind, setKind] = useState<"NOTE" | "CALL">("NOTE");
  const [body, setBody] = useState("");
  const [reference, setReference] = useState(project ?? "");

  async function add(e: FormEvent) {
    e.preventDefault();
    const result = await run(() =>
      apiRequest<AccountActionOut>("POST", `/admin/accounts/${accountId}/notes`, {
        kind,
        body,
        project_reference: reference || null,
      }),
    );
    if (result) {
      setBody("");
      router.refresh();
    }
  }

  async function remove(note: StaffNoteOut) {
    if (!window.confirm("Delete this note? This can't be undone.")) return;
    const result = await run(() =>
      apiRequest<AccountActionOut>("DELETE", `/admin/accounts/${accountId}/notes/${note.id}`),
    );
    if (result) router.refresh();
  }

  return (
    <>
      {canAdd ? (
        <form method="post" className="form" onSubmit={(e) => void add(e)}>
          <fieldset>
            <legend>What are you adding?</legend>
            <label>
              <input
                type="radio"
                name="kind"
                value="NOTE"
                checked={kind === "NOTE"}
                onChange={() => setKind("NOTE")}
              />{" "}
              A note
            </label>
            <label>
              <input
                type="radio"
                name="kind"
                value="CALL"
                checked={kind === "CALL"}
                onChange={() => setKind("CALL")}
              />{" "}
              A phone call and how it went
            </label>
          </fieldset>
          <label>
            {kind === "CALL" ? "How the call went" : "Note"}
            <textarea
              name="body"
              required
              rows={3}
              maxLength={4000}
              value={body}
              aria-invalid={fields.body ? true : undefined}
              onChange={(e) => setBody(e.target.value)}
            />
          </label>
          <label>
            Project (optional)
            <input
              name="project_reference"
              maxLength={40}
              placeholder="For example PLN-ABC123"
              value={reference}
              onChange={(e) => setReference(e.target.value)}
            />
          </label>
          <p className="hint">
            Other staff see these. Write them as if the customer might read them one day: they
            can ask for a copy of what we hold about them.
          </p>
          <FormError message={error} />
          <button type="submit" className="button" disabled={busy}>
            {kind === "CALL" ? "Log call" : "Save note"}
          </button>
        </form>
      ) : null}
      {notes.length === 0 ? (
        <p className="muted">No notes yet.</p>
      ) : (
        <ul className="plain-list" aria-label="Staff notes">
          {notes.map((n) => (
            <li key={n.id} className="panel">
              <p>
                <strong>{NOTE_KIND_LABELS[n.kind] ?? n.kind}</strong>
                {n.project_reference ? (
                  <>
                    {" "}
                    · <code>{n.project_reference}</code>
                  </>
                ) : null}
                <span className="muted">
                  {" "}
                  · {formatDateTime(n.created_at)} · {n.author_name ?? "Former staff member"}
                </span>
              </p>
              {n.subject ? <p>Subject: {n.subject}</p> : null}
              <p className="staff-note-body">{n.body}</p>
              {n.can_delete ? (
                <button
                  type="button"
                  className="button button-secondary"
                  disabled={busy}
                  onClick={() => void remove(n)}
                >
                  Delete
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
