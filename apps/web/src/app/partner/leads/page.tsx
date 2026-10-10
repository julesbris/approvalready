import type { CreditsOut, LeadOfferOut, LeadPreferencesOut } from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { NoAccess } from "@/components/app/AppShell";
import { BuyCreditsButton, LeadPreferencesForm } from "@/components/leads/PartnerLeadSettings";
import { PartnerShell } from "@/components/partners/PartnerShell";
import { formatDateTime } from "@/lib/labels";
import {
  CREDIT_KIND_LABELS,
  MATCH_STATUS_LABELS,
  TIMING_LABELS,
  groupOffers,
  leadPlace,
  money,
} from "@/lib/leads";
import { activePartnerOrganisation } from "@/lib/partners";
import { firstParam } from "@/lib/redirect";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Referrals", robots: { index: false } };

type Props = { searchParams: Promise<Record<string, string | string[] | undefined>> };

function OfferList({ offers, empty }: { offers: LeadOfferOut[]; empty: string }) {
  if (offers.length === 0) return <p className="muted">{empty}</p>;
  return (
    <ul className="task-list">
      {offers.map(({ lead }) => (
        <li key={lead.match_id} className="task">
          <span>
            <Link href={`/partner/leads/${lead.match_id}`}>
              <strong>{lead.category_label}</strong>
            </Link>{" "}
            <span className={`status status-${lead.status.toLowerCase()}`}>
              {MATCH_STATUS_LABELS[lead.status]}
            </span>
            <br />
            <span className="muted">
              {leadPlace(lead)}. {TIMING_LABELS[lead.timing]}. Offered{" "}
              {formatDateTime(lead.offered_at)}.
            </span>
          </span>
        </li>
      ))}
    </ul>
  );
}

export default async function PartnerLeadsPage({ searchParams }: Props) {
  const bought = firstParam((await searchParams).credits) === "bought";
  const session = await requireSession("/partner/leads");
  const active = activePartnerOrganisation(session);
  if (!active) redirect("/partner");
  if (!session.permissions.includes("lead.read")) {
    return (
      <PartnerShell session={session} current="leads">
        <NoAccess what="referrals" />
      </PartnerShell>
    );
  }
  const base = `/organisations/${active.organisation_id}/partner`;
  const canManage = session.permissions.includes("partner.manage");
  const canBuy = session.permissions.includes("billing.manage");
  const [offers, credits, preferences] = await Promise.all([
    serverGet<LeadOfferOut[]>(`${base}/leads`),
    serverGet<CreditsOut>(`${base}/credits`),
    serverGet<LeadPreferencesOut>(`${base}/lead-preferences`),
  ]);
  const { open, working, closed } = groupOffers(orNotFound(offers));
  const credit = orNotFound(credits);
  const prefs = orNotFound(preferences);
  return (
    <PartnerShell session={session} current="leads">
      <h1 className="page-title">Referrals</h1>
      {bought ? (
        <p className="notice">
          Thanks. Your credit appears below as soon as Stripe confirms the payment.
        </p>
      ) : null}
      <p className="muted">
        Customers who ask to be introduced are matched to checked partners by area,
        specialisation, insurance, how quickly you reply and how busy you are. Your plan never
        changes your place. You see the job and the area first; the customer&apos;s contact
        details come when you accept.
      </p>

      <section className="panel" aria-labelledby="open-title">
        <h2 id="open-title" className="section-title">
          Waiting for you
        </h2>
        <OfferList offers={open} empty="No new referrals right now. We email you when one comes in." />
      </section>
      <section className="panel" aria-labelledby="working-title">
        <h2 id="working-title" className="section-title">
          Accepted
        </h2>
        <OfferList offers={working} empty="Nothing in progress." />
      </section>

      <section className="panel" aria-labelledby="credit-title">
        <h2 id="credit-title" className="section-title">
          Fees and credit
        </h2>
        <p>
          {credit.included_limit === null
            ? "Your plan includes unlimited referrals."
            : `${credit.included_used} of the ${credit.included_limit} referrals your plan includes this month used.`}{" "}
          Referrals after that cost the fee shown before you accept, paid from your credit.
        </p>
        <p>
          <strong>Credit: {money(credit.balance_cents)}</strong>
        </p>
        {canBuy && credit.pack_price_cents ? (
          <BuyCreditsButton
            organisationId={active.organisation_id}
            priceCents={credit.pack_price_cents}
          />
        ) : null}
        {credit.entries.length > 0 ? (
          <table className="table">
            <thead>
              <tr>
                <th>When</th>
                <th>What</th>
                <th>Amount</th>
                <th>Credit after</th>
              </tr>
            </thead>
            <tbody>
              {credit.entries.map((e) => (
                <tr key={e.id}>
                  <td>{formatDateTime(e.created_at)}</td>
                  <td>
                    {CREDIT_KIND_LABELS[e.kind]}
                    {e.note ? <span className="muted"> ({e.note})</span> : null}
                  </td>
                  <td>{money(e.delta_cents)}</td>
                  <td>{money(e.balance_after_cents)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </section>

      {canManage ? (
        <section className="panel" aria-labelledby="prefs-title">
          <h2 id="prefs-title" className="section-title">
            Receiving referrals
          </h2>
          <LeadPreferencesForm organisationId={active.organisation_id} preferences={prefs} />
        </section>
      ) : null}

      {closed.length > 0 ? (
        <section className="panel" aria-labelledby="closed-title">
          <h2 id="closed-title" className="section-title">
            Finished
          </h2>
          <OfferList offers={closed} empty="" />
        </section>
      ) : null}
    </PartnerShell>
  );
}
