"use client";

import type { MarketingPostOut } from "@approvalready/shared-types";
import { useRouter } from "next/navigation";

import { useAction } from "@/components/admin/useAction";
import { FormError } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";
import {
  CHANNEL_LABELS,
  POST_STATUS_LABELS,
  formatBrisbane,
  postStatusClass,
} from "@/lib/marketing";

function PostItem({ post }: { post: MarketingPostOut }) {
  const router = useRouter();
  const { busy, error, run } = useAction();

  async function act(action: "cancel" | "retry") {
    const done = await run(() =>
      apiRequest<MarketingPostOut>("POST", `/admin/marketing/posts/${post.id}/${action}`),
    );
    if (done) router.refresh();
  }

  const when = post.posted_at ?? post.scheduled_for;
  return (
    <li className="card">
      <div>
        <strong>{post.guide_title}</strong>{" "}
        <span className={postStatusClass(post.status)}>{POST_STATUS_LABELS[post.status]}</span>
      </div>
      <div className="muted">
        {CHANNEL_LABELS[post.channel]} · {post.origin === "AUTO" ? "auto-post" : "by staff"} ·{" "}
        {post.posted_at ? "posted" : "for"} {formatBrisbane(when)}
        {post.channel === "EMAIL" && post.sent_count > 0 ? ` · sent to ${post.sent_count}` : ""}
        {post.external_url ? (
          <>
            {" · "}
            <a href={post.external_url} target="_blank" rel="noreferrer">
              View post
            </a>
          </>
        ) : null}
      </div>
      {post.error ? <p className="muted">{post.error}</p> : null}
      <details>
        <summary>{post.subject ? `Email: ${post.subject}` : "Caption"}</summary>
        <pre className="marketing-body">{post.body}</pre>
      </details>
      <FormError message={error} />
      {post.status === "SCHEDULED" ? (
        <button
          type="button"
          className="button button-secondary"
          disabled={busy}
          onClick={() => act("cancel")}
        >
          Cancel
        </button>
      ) : null}
      {post.status === "FAILED" ? (
        <button type="button" className="button" disabled={busy} onClick={() => act("retry")}>
          Try again
        </button>
      ) : null}
    </li>
  );
}

/** Staff: posts coming up, then the posting history. */
export function MarketingPosts({ posts }: { posts: MarketingPostOut[] }) {
  const upcoming = posts.filter((p) => p.status === "SCHEDULED" || p.status === "PUBLISHING");
  const history = posts.filter((p) => p.status !== "SCHEDULED" && p.status !== "PUBLISHING");
  return (
    <>
      <h3 className="subsection-title">Coming up</h3>
      {upcoming.length === 0 ? (
        <p className="muted">Nothing scheduled.</p>
      ) : (
        <ul className="card-list" aria-label="Coming up">
          {upcoming.map((p) => (
            <PostItem key={p.id} post={p} />
          ))}
        </ul>
      )}
      <h3 className="subsection-title">History</h3>
      {history.length === 0 ? (
        <p className="muted">Nothing posted yet.</p>
      ) : (
        <ul className="card-list" aria-label="Posting history">
          {history.map((p) => (
            <PostItem key={p.id} post={p} />
          ))}
        </ul>
      )}
    </>
  );
}
