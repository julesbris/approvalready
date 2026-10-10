"use client";

import type { ConversationOut } from "@approvalready/shared-types";
import { useEffect, useState } from "react";

import { useAction } from "@/components/admin/useAction";
import { FormError } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";
import { formatDateTime } from "@/lib/labels";

/** One conversation between a customer and a partner about a referral: the messages, oldest
 * first, and a box to write. Opening it marks the other side's messages as read. */
export function Conversation({
  conversation: initial,
  path,
  otherName,
  canWrite,
}: {
  conversation: ConversationOut;
  /** API path of the conversation: `${path}/messages` sends, `${path}/read` marks read. */
  path: string;
  otherName: string;
  canWrite: boolean;
}) {
  const [conversation, setConversation] = useState(initial);
  const [draft, setDraft] = useState("");
  const { busy, error, run } = useAction();
  const unread = initial.unread;

  useEffect(() => {
    if (unread > 0) void apiRequest<ConversationOut>("POST", `${path}/read`);
  }, [path, unread]);

  async function send(e: React.FormEvent) {
    e.preventDefault();
    const body = draft.trim();
    if (!body) return;
    const done = await run(() =>
      apiRequest<ConversationOut>("POST", `${path}/messages`, { body }),
    );
    if (done !== null) {
      setConversation(done);
      setDraft("");
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
              required
              onChange={(e) => setDraft(e.target.value)}
            />
          </label>
          <FormError message={error} />
          <div className="button-row">
            <button type="submit" className="button" disabled={busy || !draft.trim()}>
              Send message
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
