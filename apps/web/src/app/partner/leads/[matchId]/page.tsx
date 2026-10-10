import type { ConversationOut, LeadOfferOut } from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { NoAccess } from "@/components/app/AppShell";
import { OfferActions, OutcomeActions } from "@/components/leads/LeadActions";
import { Conversation } from "@/components/leads/Messages";
import { PartnerQuotes, QuoteForm } from "@/components/leads/QuoteActions";
import { PartnerShell } from "@/components/partners/PartnerShell";
import { formatDateTime } from "@/lib/labels";
import {
  FACTOR_LABELS,
  FIELD_LABELS,
  MATCH_STATUS_LABELS,
  OPEN_MATCH,
  TIMING_LABELS,
  WORKING,
  leadPlace,
  money,
} from "@/lib/leads";
import { activePartnerOrganisation } from "@/lib/partners";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Referral", robots: { index: false } };

type Props = { params: Promise<{ matchId: string }> };

export default async function PartnerLeadPage({ params }: Props) {
  const { matchId } = await params;
  const session = await requireSession(`/partner/leads/${matchId}`);
  const active = activePartnerOrganisation(session);
  if (!active) redirect("/partner");
  if (!session.permissions.includes("lead.read")) {
    return (
      <PartnerShell session={session} current="leads">
        <NoAccess what="referrals" />
      </PartnerShell>
    );
  }
  const offer = orNotFound(
    await serverGet<LeadOfferOut>(
      `/organisations/${active.organisation_id}/partner/leads/${matchId}`,
    ),
  );
  const { lead, fee, claim } = offer;
  const leadPath = `/organisations/${active.organisation_id}/partner/leads/${matchId}`;
  const conversation = claim ? await serverGet<ConversationOut>(`${leadPath}/messages`) : null;
  const quotes = offer.quotes ?? [];
  const canClaim = session.permissions.includes("lead.claim");
  const isOpen = OPEN_MATCH.includes(lead.status) && lead.lead_status === "OPEN";
  return (
    <PartnerShell session={session} current="leads">
      <p>
        <Link href="/partner/leads">All referrals</Link>
      </p>
      <h1 className="page-title">
        {lead.category_label}{" "}
        <span className={`status status-${lead.status.toLowerCase()}`}>
          {MATCH_STATUS_LABELS[lead.status]}
        </span>
      </h1>

      <section className="panel" aria-labelledby="job-title">
        <h2 id="job-title" className="section-title">
          The job
        </h2>
        <dl className="facts">
          <dt>Where</dt>
          <dd>{leadPlace(lead)}</dd>
          <dt>When</dt>
          <dd>{TIMING_LABELS[lead.timing]}</dd>
          <dt>Partners wanted</dt>
          <dd>
            {lead.max_claims} ({lead.claims_left} place{lead.claims_left === 1 ? "" : "s"} left)
          </dd>
          <dt>Offered</dt>
          <dd>{formatDateTime(lead.offered_at)}</dd>
          {isOpen ? (
            <>
              <dt>Open until</dt>
              <dd>{formatDateTime(lead.expires_at)}</dd>
            </>
          ) : null}
        </dl>
        {lead.summary ? <p>&ldquo;{lead.summary}&rdquo;</p> : null}
        {lead.requirements.length > 0 ? (
          <>
            <p className="muted">What our assessment says they need:</p>
            <ul>
              {lead.requirements.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          </>
        ) : null}
      </section>

      {claim ? (
        <section className="panel" aria-labelledby="contact-title">
          <h2 id="contact-title" className="section-title">
            Contact details
          </h2>
          <dl className="facts">
            {claim.released_fields.map((f) => (
              <div key={f}>
                <dt>{FIELD_LABELS[f as keyof typeof FIELD_LABELS] ?? f}</dt>
                <dd>{String(claim.contact[f] ?? "")}</dd>
              </div>
            ))}
          </dl>
          <p className="muted">
            Accepted {formatDateTime(claim.claimed_at)}.{" "}
            {claim.included
              ? "Included in your plan."
              : claim.fee_cents > 0
                ? `Fee ${money(claim.fee_cents)}${claim.refunded_at ? ", refunded" : ""}.`
                : "No fee."}{" "}
            The customer agreed to be contacted about this job only.
          </p>
        </section>
      ) : null}

      {isOpen ? (
        <OfferActions
          organisationId={active.organisation_id}
          matchId={lead.match_id}
          fee={fee}
          canClaim={canClaim}
        />
      ) : null}
      {claim && (quotes.length > 0 || (canClaim && WORKING.includes(lead.status))) ? (
        <section className="panel" aria-labelledby="quote-title">
          <h2 id="quote-title" className="section-title">
            Your quote
          </h2>
          <PartnerQuotes
            organisationId={active.organisation_id}
            matchId={lead.match_id}
            quotes={quotes}
            canClaim={canClaim}
          />
          {canClaim && WORKING.includes(lead.status) ? (
            <QuoteForm
              key={quotes[0]?.id ?? "new"}
              organisationId={active.organisation_id}
              matchId={lead.match_id}
              revising={quotes[0]?.status === "SENT" ? quotes[0] : null}
            />
          ) : null}
        </section>
      ) : null}
      {conversation?.ok ? (
        <section className="panel" id="messages" aria-labelledby="messages-title">
          <h2 id="messages-title" className="section-title">
            Messages with the customer
            {offer.unread_messages > 0 ? (
              <span className="badge">{offer.unread_messages} new</span>
            ) : null}
          </h2>
          <Conversation
            conversation={conversation.data}
            path={leadPath}
            otherName="Customer"
            canWrite={canClaim}
          />
          <p className="muted">
            Keep the conversation about this job. Don&apos;t ask for passwords or card details.
          </p>
        </section>
      ) : null}
      {claim ? (
        <OutcomeActions
          organisationId={active.organisation_id}
          matchId={lead.match_id}
          status={lead.status}
          canClaim={canClaim}
        />
      ) : null}

      <section className="panel" aria-labelledby="why-title">
        <h2 id="why-title" className="section-title">
          Why you were matched ({Math.round(lead.score)} of 100)
        </h2>
        <ul>
          {lead.score_breakdown.map((f) => (
            <li key={f.factor}>
              <strong>{FACTOR_LABELS[f.factor] ?? f.factor}</strong>: {f.points} of {f.max}.{" "}
              <span className="muted">{f.why}</span>
            </li>
          ))}
        </ul>
      </section>
    </PartnerShell>
  );
}
