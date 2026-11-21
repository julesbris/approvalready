"use client";

import type { AttachmentOut, ConversationOut } from "@approvalready/shared-types";
import { useEffect, useRef, useState } from "react";

import { useAction } from "@/components/admin/useAction";
import { FormError } from "@/components/auth/FormStatus";
import { apiRequest, apiUpload } from "@/lib/client-api";
import { ACCEPT, SCAN_LABELS, formatBytes, waitUntil } from "@/lib/documents";
import { formatDateTime } from "@/lib/labels";

/** A file sent with a message: a download link once it passed the virus check. */
export function Attachment({ file, path }: { file: AttachmentOut; path: string }) {
  const clean = file.scan_status === "CLEAN";
  return (
    <p className="message-file">
      {clean ? (
        <a href={`/api/v1${path}/files/${file.id}/content`} download={file.filename}>
          {file.filename}
        </a>
      ) : (
        <span>{file.filename}</span>
      )}{" "}
      <span className="muted">
        ({formatBytes(file.size_bytes)}
        {clean ? "" : ` · ${SCAN_LABELS[file.scan_status]}`})
      </span>
    </p>
  );
}

const pendingFile = (c: ConversationOut) =>
  c.messages.some((m) => m.attachment?.scan_status === "PENDING");

/** One conversation between a customer and a partner about a referral: the messages, oldest
 * first, and a box to write. Opening it marks the other side's messages as read. */
export function Conversation({
  conversation: initial,
  path,
  otherName,
  canWrite,
}: {
  conversation: ConversationOut;
  /** API path of the conversation: `${path}/messages` reads and sends, `${path}/files`
   * sends a file, `${path}/read` marks read. */
  path: string;
  otherName: string;
  canWrite: boolean;
}) {
  const [conversation, setConversation] = useState(initial);
  const [draft, setDraft] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const { busy, error, run } = useAction();
  const unread = initial.unread;

  useEffect(() => {
    if (unread > 0) void apiRequest<ConversationOut>("POST", `${path}/read`);
  }, [path, unread]);

  async function send(e: React.FormEvent) {
    e.preventDefault();
    const body = draft.trim();
    if (!body && !file) return;
    const done = await run(() =>
      file
        ? apiUpload<ConversationOut>(`${path}/files`, file, body ? { body } : {})
        : apiRequest<ConversationOut>("POST", `${path}/messages`, { body }),
    );
    if (done !== null) {
      setConversation(done);
      setDraft("");
      setFile(null);
      if (fileInput.current) fileInput.current.value = "";
      // A file is checked for viruses in the background: show it once it's ready.
      if (pendingFile(done)) {
        const result = await waitUntil(
          () => apiRequest<ConversationOut>("GET", `${path}/messages`),
          (c) => !pendingFile(c),
        );
        if (result.ok) setConversation(result.data);
      }
    }
  }

  const { messages } = conversation;
  return (
    <>
      {messages.length === 0 ? (
        <p className="muted">No messages yet.</p>
      ) : (
        <ol className="message-list" aria-label={`Messages with ${otherName}`}>
          {messages.map((m) => (
            <li key={m.id} className={m.from_you ? "message message-mine" : "message"}>
              <p className="message-meta">
                <strong>{m.from_you ? "You" : otherName}</strong>, {formatDateTime(m.sent_at)}
                {!m.from_you && !m.read_at ? (
                  <span className="badge">New</span>
                ) : null}
                {m.from_you && m.read_at ? <span className="muted"> · Seen</span> : null}
              </p>
              <p className="message-body">{m.body}</p>
              {m.attachment ? <Attachment file={m.attachment} path={path} /> : null}
            </li>
          ))}
        </ol>
      )}
      {conversation.can_send && canWrite ? (
        <form method="post" onSubmit={(e) => void send(e)}>
          <label>
            Message to {otherName}
            <textarea
              value={draft}
              maxLength={4000}
              rows={3}
              required={!file}
              onChange={(e) => setDraft(e.target.value)}
            />
          </label>
          <label>
            Attach a file (optional)
            <input
              ref={fileInput}
              type="file"
              accept={ACCEPT}
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
            <span className="muted">
              Plans, photos, quotes: PDF, Word, Excel, images or text. Checked for viruses
              before {otherName} can open it.
            </span>
          </label>
          <FormError message={error} />
          <div className="button-row">
            <button type="submit" className="button" disabled={busy || (!draft.trim() && !file)}>
              {file ? "Send file" : "Send message"}
            </button>
          </div>
        </form>
      ) : !conversation.can_send ? (
        <p className="muted">This job is finished, so the conversation is read-only.</p>
      ) : null}
    </>
  );
}

/** The customer's conversations on a project: one per partner who accepted a request. */
export function CustomerMessages({
  organisationId,
  projectId,
  conversations,
  canWrite,
}: {
  organisationId: string;
  projectId: string;
  conversations: ConversationOut[];
  canWrite: boolean;
}) {
  if (conversations.length === 0) {
    return (
      <p className="muted">
        When a partner accepts your request, you can message them here about the job.
      </p>
    );
  }
  const base = `/organisations/${organisationId}/projects/${projectId}/conversations`;
  return (
    <>
      {conversations.map((c) => (
        <section
          key={c.match_id}
          id={`messages-${c.match_id}`}
          aria-label={`Messages with ${c.partner_name}`}
        >
          <h3 className="card-title">
            {c.partner_name} <span className="muted">({c.category_label})</span>
            {c.unread > 0 ? <span className="badge">{c.unread} new</span> : null}
          </h3>
          <Conversation
            conversation={c}
            path={`${base}/${c.match_id}`}
            otherName={c.partner_name}
            canWrite={canWrite}
          />
        </section>
      ))}
      <p className="muted">
        Messages stay here for both of you. Don&apos;t send passwords or payment card details.
      </p>
    </>
  );
}
