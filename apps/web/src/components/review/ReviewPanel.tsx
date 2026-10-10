"use client";

import type { CheckoutOut, PriceOut, ReviewOut, ReviewSummary } from "@approvalready/shared-types";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { useAction } from "@/components/admin/useAction";
import { FormError } from "@/components/auth/FormStatus";
import { formatMoney } from "@/lib/billing";
import { type ApiResult, apiRequest } from "@/lib/client-api";
import { formatDateTime } from "@/lib/labels";
import { formatDate } from "@/lib/questionnaire";
import { DECISION_DONE, REVIEW_STATUS_LABELS, isOpen, reviewerName } from "@/lib/review";

type Props = {
  organisationId: string;
  projectId: string;
  assessmentId: string;
  /** Whether this is the project's latest assessment (only that one can be sent). */
  isLatest: boolean;
  /** The review on this assessment, if any. */
  review: ReviewOut | null;
  /** The project's open review, when it is about another assessment (one at a time). */
  openElsewhere: ReviewSummary | null;
  canWrite: boolean;
  /** The price of a review, when reviews are paid for. */
  price?: PriceOut | null;
  /** Back from Stripe Checkout: "done" or "cancelled". */
  paymentReturn?: string | null;
};

export function Conversation({
  review,
  onSend,
  busy,
  canWrite,
  who,
}: {
  review: ReviewOut;
  onSend: (body: string) => Promise<boolean>;
  busy: boolean;
  canWrite: boolean;
  who: "customer" | "reviewer";
}) {
  const [body, setBody] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (await onSend(body)) setBody("");
  }
  return (
    <div>
      <h3 className="finding-label">Messages</h3>
      {review.comments.length === 0 ? <p className="muted">No messages yet.</p> : null}
      <ul className="task-list" aria-label="Messages">
        {review.comments.map((c) => (
          <li key={c.id} className="task">
            <span>
              <strong>
                {c.author_role === "REVIEWER"
                  ? who === "reviewer"
                    ? "You"
                    : "Reviewer"
                  : who === "customer"
                    ? (c.author_name ?? "You")
                    : "Customer"}
              </strong>
              : {c.body}
            </span>
            <span className="muted">{formatDateTime(c.created_at)}</span>
          </li>
        ))}
      </ul>
      {canWrite ? (
        <form method="post" className="form" onSubmit={submit}>
          <label>
            {who === "customer" ? "Message your reviewer" : "Message the customer"}
            <textarea
              value={body}
              maxLength={4000}
              rows={3}
              onChange={(e) => setBody(e.target.value)}
              required
            />
          </label>
          <div className="button-row">
            <button type="submit" className="button-secondary" disabled={busy || !body.trim()}>
              Send
            </button>
          </div>
        </form>
      ) : null}
    </div>
  );
}

export function Decisions({ review }: { review: ReviewOut }) {
  if (review.decisions.length === 0) return null;
  return (
    <ul className="task-list" aria-label="Reviewer decisions">
      {review.decisions.map((d) => (
        <li key={d.id} className="task">
          <span>
            <strong>{DECISION_DONE[d.decision]}</strong>
            {d.notes ? `: ${d.notes}` : ""}
          </span>
          <span className="muted">{formatDateTime(d.created_at)}</span>
        </li>
      ))}
    </ul>
  );
}

/** The customer's side of professional review on an assessment page. */
export function ReviewPanel(props: Props) {
  const { organisationId, projectId, assessmentId, isLatest, openElsewhere, canWrite } = props;
  const { price = null, paymentReturn = null } = props;
  const router = useRouter();
  const [review, setReview] = useState(props.review);
  const [message, setMessage] = useState("");
  const { busy, error, run } = useAction();
  const org = `/organisations/${organisationId}`;

  async function act(call: () => Promise<ApiResult<ReviewOut>>): Promise<boolean> {
    const data = await run(call);
    if (!data) return false;
    setReview(data);
    router.refresh();
    return true;
  }

  /** Off to Stripe's checkout page; the review moves on once Stripe confirms payment. */
  async function pay(reviewId: string): Promise<void> {
    const data = await run(() =>
      apiRequest<CheckoutOut>("POST", `${org}/reviews/${reviewId}/checkout`),
    );
    if (data) window.location.assign(data.url);
  }

  const request = async (event: FormEvent) => {
    event.preventDefault();
    const data = await run(() =>
      apiRequest<ReviewOut>("POST", `${org}/projects/${projectId}/reviews`, {
        assessment_id: assessmentId,
        message: message.trim() || null,
      }),
    );
    if (!data) return;
    setReview(data);
    if (data.status === "PAYMENT_PENDING") await pay(data.id);
    else router.refresh();
  };

  if (openElsewhere) {
    const canMove = canWrite && isLatest && openElsewhere.status === "CHANGES_REQUIRED";
    return (
      <section className="panel" aria-labelledby="review-title">
        <h2 id="review-title" className="section-title">
          Professional review
        </h2>
        <p>
          A review of{" "}
          <Link href={`/projects/${projectId}/assessments/${openElsewhere.assessment_id}`}>
            another assessment of this project
          </Link>{" "}
          is under way ({REVIEW_STATUS_LABELS[openElsewhere.status].toLowerCase()}).
        </p>
        {canMove ? (
          <>
            <p className="muted">
              Your reviewer asked for changes. If this assessment includes them, send it to them.
            </p>
            <FormError message={error} />
            <button
              type="button"
              className="button"
              disabled={busy}
              onClick={() =>
                act(() =>
                  apiRequest<ReviewOut>("POST", `${org}/reviews/${openElsewhere.id}/resubmit`, {
                    assessment_id: assessmentId,
                  }),
                )
              }
            >
              Send this assessment to your reviewer
            </button>
          </>
        ) : null}
      </section>
    );
  }

  if (!review) {
    if (!canWrite || !isLatest) return null;
    return (
      <section className="panel" aria-labelledby="review-title">
        <h2 id="review-title" className="section-title">
          Ask a professional to check this
        </h2>
        <p>
          A qualified professional, such as a town planner, can review this assessment, correct
          anything that doesn&apos;t fit your situation and tell you what to do next.
        </p>
        <p className="muted">
          Your reviewer will see your answers, this assessment, the files you attach as evidence
          and any files you choose to share with them. Nobody else outside your organisation will.
        </p>
        {price ? (
          <p>
            A review costs <strong>{formatMoney(price.amount_cents, price.currency)}</strong>{" "}
            (including GST), paid securely through Stripe. We assign your reviewer once the payment
            is confirmed.
          </p>
        ) : null}
        <form method="post" className="form" onSubmit={(e) => void request(e)}>
          <label>
            Anything you&apos;d like them to look at? (optional)
            <textarea
              value={message}
              maxLength={2000}
              rows={3}
              onChange={(e) => setMessage(e.target.value)}
            />
          </label>
          <FormError message={error} />
          <div className="button-row">
            <button type="submit" className="button" disabled={busy}>
              {price ? "Request and pay" : "Request a professional review"}
            </button>
          </div>
        </form>
      </section>
    );
  }

  const open = isOpen(review.status);
  if (review.status === "PAYMENT_PENDING") {
    const amount = review.payment
      ? formatMoney(review.payment.amount_cents, review.payment.currency)
      : null;
    return (
      <section className="panel" aria-labelledby="review-title">
        <h2 id="review-title" className="section-title">
          Professional review
        </h2>
        <p>
          <span className="status status-payment_pending">Waiting for payment</span>{" "}
          {paymentReturn === "done"
            ? "Thanks. We're confirming your payment with Stripe; this usually takes a few seconds."
            : "Your review starts once it's paid for."}
        </p>
        {paymentReturn === "done" ? (
          <p className="muted">Reload this page in a moment to see your review move on.</p>
        ) : null}
        {paymentReturn === "cancelled" ? (
          <p className="notice">The payment wasn&apos;t completed. You can try again.</p>
        ) : null}
        <FormError message={error} />
        {canWrite ? (
          <div className="button-row">
            <button
              type="button"
              className="button"
              disabled={busy}
              onClick={() => void pay(review.id)}
            >
              {amount ? `Pay ${amount}` : "Pay now"}
            </button>
            <button
              type="button"
              className="button-link"
              disabled={busy}
              onClick={() => {
                if (window.confirm("Cancel this review request?")) {
                  void act(() => apiRequest<ReviewOut>("POST", `${org}/reviews/${review.id}/cancel`));
                }
              }}
            >
              Cancel the request
            </button>
          </div>
        ) : null}
      </section>
    );
  }
  return (
    <section className="panel" aria-labelledby="review-title">
      <h2 id="review-title" className="section-title">
        Professional review
      </h2>
      <p>
        <span className={`status status-${review.status.toLowerCase()}`}>
          {REVIEW_STATUS_LABELS[review.status]}
        </span>{" "}
        {review.professional
          ? `Reviewer: ${reviewerName(review.professional)}.`
          : "We're finding a reviewer for you."}
        {review.due_on && open ? ` Expected by ${formatDate(review.due_on)}.` : ""}
      </p>
      {review.status === "CHANGES_REQUIRED" ? (
        <p className="notice">
          Your reviewer asked for changes. Make them (update your answers and run a new assessment
          if needed, or add files), then send it back.
        </p>
      ) : null}
      <Decisions review={review} />
      {review.overrides.length > 0 ? (
        <p className="muted">
          The reviewer changed {new Set(review.overrides.map((o) => o.finding_id)).size} finding(s);
          the changes are shown below with the original result.
        </p>
      ) : null}
      <FormError message={error} />
      <Conversation
        review={review}
        busy={busy}
        canWrite={canWrite && open}
        who="customer"
        onSend={(body) =>
          act(() => apiRequest<ReviewOut>("POST", `${org}/reviews/${review.id}/comments`, { body }))
        }
      />
      {canWrite && open ? (
        <div className="button-row">
          {review.status === "CHANGES_REQUIRED" ? (
            <button
              type="button"
              className="button"
              disabled={busy}
              onClick={() =>
                act(() =>
                  apiRequest<ReviewOut>("POST", `${org}/reviews/${review.id}/resubmit`, {
                    assessment_id: isLatest ? assessmentId : null,
                  }),
                )
              }
            >
              Send back to your reviewer
            </button>
          ) : null}
          <button
            type="button"
            className="button-link"
            disabled={busy}
            onClick={() => {
              if (window.confirm("Cancel this review?")) {
                void act(() => apiRequest<ReviewOut>("POST", `${org}/reviews/${review.id}/cancel`));
              }
            }}
          >
            Cancel the review
          </button>
        </div>
      ) : null}
    </section>
  );
}
