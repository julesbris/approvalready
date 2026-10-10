import type { PartnerOut } from "@approvalready/shared-types";
import Link from "next/link";

import { ResubmitButton } from "@/components/partners/ResubmitButton";
import { SUBSCRIPTION_STATUS_LABELS, limitLabel } from "@/lib/billing";
import { formatDateTime } from "@/lib/labels";
import { LIMIT_LABELS, PARTNER_STATUS_LABELS, areaLabel } from "@/lib/partners";

const STATUS_TEXT: Record<PartnerOut["status"], string> = {
  APPLIED: "We have your application and will check it soon. We email you when we have decided.",
  UNDER_REVIEW:
    "We are checking your ABN, licences and insurance. We email you when we have decided.",
  ACTIVE: "Your partner account is approved.",
  SUSPENDED: "Your partner account is suspended, so it doesn't receive referrals.",
  REJECTED: "We couldn't approve your application yet.",
};

/** The partner's dashboard: where the account stands, what receives referrals, the plan. */
export function PartnerDashboard({
  organisationId,
  partner,
  canManage,
}: {
  organisationId: string;
  partner: PartnerOut;
  canManage: boolean;
}) {
  const counting = partner.categories.filter((c) => c.counts);
  const plan = partner.plan;
  return (
    <>
      <section className="panel" aria-labelledby="status-title">
        <h2 id="status-title" className="section-title">
          {partner.name}{" "}
          <span className={`status status-${partner.status.toLowerCase()}`}>
            {PARTNER_STATUS_LABELS[partner.status]}
          </span>
        </h2>
        <p>{STATUS_TEXT[partner.status]}</p>
        {partner.status_reason ? (
          <p>
            <strong>Our reason:</strong> {partner.status_reason}
          </p>
        ) : null}
        {partner.status === "REJECTED" && canManage ? (
          <>
            <p className="muted">
              Fix what we asked for in your <Link href="/partner/profile">profile</Link>, then
              send it back to us.
            </p>
            <ResubmitButton organisationId={organisationId} />
          </>
        ) : null}
      </section>

      <section className="panel" aria-labelledby="referrals-title">
        <h2 id="referrals-title" className="section-title">
          Referrals
        </h2>
        {partner.receiving_referrals ? (
          <p>
            You can receive referrals for {counting.map((c) => c.label).join(", ")} in{" "}
            {partner.service_areas
              .filter((a) => a.counts)
              .map(areaLabel)
              .join("; ")}
            .
          </p>
        ) : (
          <>
            <p>You can&apos;t receive referrals yet:</p>
            <ul>
              {partner.problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          </>
        )}
        <p className="muted">
          Customers are matched to partners by category and area once referrals open. Until then,
          keep your <Link href="/partner/profile">profile</Link> current: categories, areas and
          licences.
        </p>
      </section>

      {plan ? (
        <section className="panel" aria-labelledby="plan-title">
          <h2 id="plan-title" className="section-title">
            Your plan: {plan.name}
            {plan.status ? (
              <>
                {" "}
                <span className={`status status-${plan.status.toLowerCase()}`}>
                  {SUBSCRIPTION_STATUS_LABELS[plan.status]}
                </span>
              </>
            ) : null}
          </h2>
          {plan.grace_ends_at ? (
            <p className="notice">
              Your last payment failed. Update your card by {formatDateTime(plan.grace_ends_at)} to
              keep your plan; after that your account falls back to the free plan&apos;s limits.
            </p>
          ) : null}
          <ul className="task-list" aria-label="Plan limits">
            {plan.limits.map((l) => (
              <li key={l.feature} className="task">
                <span>{LIMIT_LABELS[l.feature] ?? l.description}</span>
                <span>
                  {l.in_use} of {limitLabel(l.limit)}
                </span>
              </li>
            ))}
          </ul>
          <p>
            <Link href="/partner/billing">Plan and billing</Link>
          </p>
        </section>
      ) : null}
    </>
  );
}
