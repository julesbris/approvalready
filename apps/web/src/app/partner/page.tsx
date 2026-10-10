import type { PartnerOut } from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";

import { SwitchButton } from "@/components/organisations/SwitchButton";
import { PartnerDashboard } from "@/components/partners/PartnerDashboard";
import { PartnerShell } from "@/components/partners/PartnerShell";
import { activePartnerOrganisation, partnerOrganisations } from "@/lib/partners";
import { firstParam } from "@/lib/redirect";
import { getSession, orNotFound, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Partners" };

type Props = { searchParams: Promise<Record<string, string | string[] | undefined>> };

function Explainer() {
  return (
    <section className="panel">
      <h1 className="page-title">Become an ApprovalReady partner</h1>
      <p className="lede">
        Our customers find out which approvals, licences and checks they need. Partners are the
        professionals and trades who help them get there: certifiers, planners, surveyors,
        marine surveyors, accountants and more.
      </p>
      <ol>
        <li>Apply with your ABN, the work you do, where you work and your licences.</li>
        <li>We check your ABN, licences and insurance against the public registers.</li>
        <li>Once approved, you can be referred for each category we have checked.</li>
      </ol>
      <p className="muted">
        Every partner starts on the free plan. Paid plans cover more categories, more service
        areas and more people in your account.
      </p>
    </section>
  );
}

export default async function PartnerHomePage({ searchParams }: Props) {
  const applied = firstParam((await searchParams).applied) === "1";
  const session = await getSession();
  if (!session) {
    return (
      <PartnerShell session={null}>
        <Explainer />
        <div className="button-row">
          <Link className="button" href="/register">
            Create an account
          </Link>
          <Link className="button-secondary" href="/login?next=/partner/apply">
            Sign in to apply
          </Link>
        </div>
      </PartnerShell>
    );
  }
  const active = activePartnerOrganisation(session);
  if (!active) {
    const others = partnerOrganisations(session);
    return (
      <PartnerShell session={session}>
        {others.length > 0 ? (
          <section className="panel">
            <h1 className="page-title">Your partner accounts</h1>
            <ul className="task-list">
              {others.map((o) => (
                <li key={o.organisation_id} className="task">
                  <span>{o.name}</span>
                  <SwitchButton organisationId={o.organisation_id} name={o.name} />
                </li>
              ))}
            </ul>
          </section>
        ) : (
          <Explainer />
        )}
        <div className="button-row">
          <Link className="button" href="/partner/apply">
            Apply to become a partner
          </Link>
        </div>
      </PartnerShell>
    );
  }
  const partner = orNotFound(
    await serverGet<PartnerOut>(`/organisations/${active.organisation_id}/partner`),
  );
  return (
    <PartnerShell session={session} current="dashboard">
      <h1 className="page-title">Partner dashboard</h1>
      {applied ? (
        <p className="notice">
          Thanks, we have your application. We have emailed you a copy of what happens next.
        </p>
      ) : null}
      <PartnerDashboard
        organisationId={active.organisation_id}
        partner={partner}
        canManage={session.permissions.includes("partner.manage")}
      />
    </PartnerShell>
  );
}
