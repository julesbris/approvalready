"use client";

import type { PlanCheckoutOut, PlanStartOut, ProjectPlanOut } from "@approvalready/shared-types";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { useAction } from "@/components/admin/useAction";
import { FormError, FormNotice } from "@/components/auth/FormStatus";
import { formatMoney } from "@/lib/billing";
import { apiRequest } from "@/lib/client-api";

const WHAT_YOU_GET = [
  "Every step from your checklist on a timeline, in the order to do them, with suggested dates",
  "A due date, an owner and notes on each step, and your files kept against it",
  "Fees, forms, contacts and what commonly goes wrong, right next to each step",
  "Checked partners in your area suggested for each part, with their phone, email and website",
  "Follow-up calls added in one click, with an email reminder on the day",
  "Progress at a glance: what's done, what's due this week and what's overdue",
];

/** What a project plan is, what it costs, and starting one (or paying for one waiting). */
export function PlanOffer({
  organisationId,
  projectId,
  plan,
  hasAssessment,
  canWrite,
  paymentReturn,
}: {
  organisationId: string;
  projectId: string;
  plan: ProjectPlanOut;
  hasAssessment: boolean;
  canWrite: boolean;
  paymentReturn: string | null;
}) {
  const router = useRouter();
  const { busy, error, run } = useAction();
  const base = `/organisations/${organisationId}/projects/${projectId}/plan`;
  const { offer } = plan;
  const pending = plan.status === "PAYMENT_PENDING";

  async function start() {
    const result = await run(() => apiRequest<PlanStartOut>("POST", base));
    if (!result) return;
    if (result.checkout_url) window.location.assign(result.checkout_url);
    else router.refresh();
  }

  async function pay() {
    const result = await run(() => apiRequest<PlanCheckoutOut>("POST", `${base}/checkout`));
    if (result) window.location.assign(result.url);
  }

  async function cancel() {
    if (await run(() => apiRequest<ProjectPlanOut>("POST", `${base}/cancel`))) router.refresh();
  }

  return (
    <section className="panel plan-offer" aria-labelledby="plan-offer-title">
      <h2 id="plan-offer-title" className="section-title">
        {pending ? "Your project plan is waiting for payment" : "Manage this project online"}
      </h2>
      {pending && paymentReturn === "done" ? (
        <FormNotice>
          Thanks. Your plan starts as soon as the payment is confirmed, usually within a minute.
          Refresh this page shortly.
        </FormNotice>
      ) : null}
      <p>{offer.product_description}</p>
      <ul className="plan-benefits">
        {WHAT_YOU_GET.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      <p className="plan-price">
        {offer.included_in_membership ? (
          <>
            <strong>Included in your ApprovalReady Plus membership.</strong> No extra cost.
          </>
        ) : offer.on_sale && offer.price_cents !== null ? (
          <>
            <strong>{formatMoney(offer.price_cents, offer.currency ?? "AUD")}</strong> once, for
            this project. No subscription.
          </>
        ) : (
          <>
            <strong>Free while we launch.</strong> Start it now and keep it.
          </>
        )}
      </p>
      {offer.membership_on_sale && !pending ? (
        <p className="muted">
          Have more than one project? <Link href="/membership">ApprovalReady Plus</Link> includes
          a plan for every project, and your first month is free.
        </p>
      ) : null}
      <FormError message={error} />
      {!canWrite ? (
        <p className="muted">Ask someone who can edit this project to start the plan.</p>
      ) : !hasAssessment ? (
        <p>
          The plan is built from your assessment.{" "}
          <Link href={`/projects/${projectId}`}>Answer the questions and run it first</Link>.
        </p>
      ) : pending ? (
        <div className="button-row">
          <button type="button" className="button" disabled={busy} onClick={pay}>
            Pay and start the plan
          </button>
          <button
            type="button"
            className="button button-secondary"
            disabled={busy}
            onClick={cancel}
          >
            Cancel
          </button>
        </div>
      ) : (
        <div className="button-row">
          <button type="button" className="button" disabled={busy} onClick={start}>
            {offer.on_sale ? "Buy the project plan" : "Start my project plan"}
          </button>
        </div>
      )}
    </section>
  );
}
