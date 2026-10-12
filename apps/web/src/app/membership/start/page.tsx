import type { OrganisationOut, PlusMembershipOut } from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

import { AppShell } from "@/components/app/AppShell";
import { FormNotice } from "@/components/auth/FormStatus";
import { StartMembership } from "@/components/billing/StartMembership";
import { TrialTimeline } from "@/components/billing/TrialTimeline";
import { longDate, plusPrice } from "@/lib/membership";
import { firstParam } from "@/lib/redirect";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Start ApprovalReady Plus", robots: { index: false } };

type Props = { searchParams: Promise<Record<string, string | string[] | undefined>> };

/** One step: check the price and dates, then add a card on Stripe's page. */
export default async function StartMembershipPage({ searchParams }: Props) {
  const checkout = firstParam((await searchParams).checkout) ?? null;
  const session = await requireSession("/membership/start");
  const orgId = session.active_organisation_id;
  const organisation = orgId
    ? orNotFound(await serverGet<OrganisationOut>(`/organisations/${orgId}`))
    : null;
  const billingUrl = orgId ? `/account/organisations/${orgId}/billing` : "/account";

  let body: ReactNode;
  if (!organisation || organisation.kind === "PARTNER" || organisation.kind === "PLATFORM_ADMIN") {
    body = (
      <p>
        ApprovalReady Plus is for your own account or your business. Switch to it from{" "}
        <Link href="/account">Your account</Link>, then come back here.
      </p>
    );
  } else if (!organisation.permissions.includes("billing.manage")) {
    body = (
      <p>
        Only the people who handle billing for {organisation.name} can start a membership. Ask them,
        or switch to your own account from <Link href="/account">Your account</Link>.
      </p>
    );
  } else {
    const plus = orNotFound(
      await serverGet<PlusMembershipOut>(`/organisations/${organisation.id}/billing/membership`),
    );
    const { offer, subscription } = plus;
    const price = plusPrice(offer);
    if (subscription) {
      body = (
        <>
          <FormNotice>
            {subscription.status === "TRIALING" && subscription.trial_end
              ? `You're in. Your free month runs until ${longDate(subscription.trial_end)}${subscription.cancel_at_period_end ? ", and you've cancelled, so nothing will be charged." : `. Then it's ${price ?? "the monthly price"}, charged to your saved card. We'll email you a reminder first.`}`
              : "You're a member of ApprovalReady Plus."}
          </FormNotice>
          <p>
            Every project now gets its project plan included. Open a project and choose{" "}
            <strong>Start my project plan</strong>.
          </p>
          <div className="button-row">
            <Link className="button" href="/projects">
              Go to my projects
            </Link>
            <Link className="button button-secondary" href={billingUrl}>
              Billing
            </Link>
          </div>
        </>
      );
    } else if (checkout === "done") {
      body = (
        <FormNotice>
          Thanks, your card is saved. We&apos;re confirming it with Stripe; refresh this page in a
          moment to see your membership.
        </FormNotice>
      );
    } else if (plus.other_plan) {
      body = (
        <p>
          You already have {plus.other_plan}. Cancel it in <Link href={billingUrl}>Billing</Link>{" "}
          first, then come back here.
        </p>
      );
    } else if (!offer.on_sale) {
      body = (
        <p>
          ApprovalReady Plus isn&apos;t open yet. Everything else on ApprovalReady is free to use in
          the meantime.
        </p>
      );
    } else {
      const trial = plus.trial_available && offer.trial_days > 0;
      body = (
        <>
          {checkout === "cancelled" ? (
            <FormNotice>No card was added and nothing was charged.</FormNotice>
          ) : null}
          <p className="lede">
            {trial
              ? `Free for ${offer.trial_days} days, then ${price}. You add your card now and pay nothing today.`
              : `${price}. You've had your free month already, so this starts straight away.`}
          </p>
          <TrialTimeline offer={offer} trial={trial} title={`For ${organisation.name}`} />
          <StartMembership organisationId={organisation.id} trial={trial} />
          <p className="muted">
            You&apos;ll add your card on Stripe&apos;s secure page; we never see it. Cancel any time
            in Billing{trial ? ` before day ${offer.trial_days + 1} and you pay nothing` : ""}. By
            continuing you agree to the <Link href="/terms">Terms of Use</Link>.
          </p>
        </>
      );
    }
  }

  return (
    <AppShell session={session}>
      <p className="breadcrumb">
        <Link href="/membership">ApprovalReady Plus</Link>
      </p>
      <h1 className="page-title">Start ApprovalReady Plus</h1>
      <section className="panel plus-start">{body}</section>
    </AppShell>
  );
}
