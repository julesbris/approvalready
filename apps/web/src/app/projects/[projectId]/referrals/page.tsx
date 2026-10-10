import type {
  CustomerQuoteOut,
  ProjectDetailOut,
  ReferralOptionsOut,
  ReferralOut,
} from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";

import { AppShell, NoAccess } from "@/components/app/AppShell";
import { FormNotice } from "@/components/auth/FormStatus";
import { CustomerQuotes } from "@/components/leads/CustomerQuotes";
import { ReferralForm } from "@/components/leads/ReferralForm";
import { ReferralList } from "@/components/leads/ReferralList";
import { firstParam } from "@/lib/redirect";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Introductions", robots: { index: false } };

type Props = {
  params: Promise<{ projectId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

/** The customer's introductions to partners for a project, and (from an assessment) the form
 * to ask for one. */
export default async function ReferralsPage({ params, searchParams }: Props) {
  const { projectId } = await params;
  const query = await searchParams;
  const assessmentId = firstParam(query.assessment) ?? null;
  const sent = firstParam(query.sent) === "1";
  const session = await requireSession(`/projects/${projectId}/referrals`);
  const orgId = session.active_organisation_id;
  if (!orgId || !session.permissions.includes("project.read")) {
    return (
      <AppShell session={session}>
        <NoAccess what="projects" />
      </AppShell>
    );
  }
  const canWrite = session.permissions.includes("project.write");
  const base = `/organisations/${orgId}/projects/${projectId}`;
  const [project, referrals, quotes, options] = await Promise.all([
    serverGet<ProjectDetailOut>(base),
    serverGet<ReferralOut[]>(`${base}/referrals`),
    serverGet<CustomerQuoteOut[]>(`${base}/quotes`),
    assessmentId && canWrite
      ? serverGet<ReferralOptionsOut>(
          `${base}/referrals/options?assessment_id=${encodeURIComponent(assessmentId)}`,
        )
      : Promise.resolve(null),
  ]);
  const found = orNotFound(project);
  return (
    <AppShell session={session}>
      <p className="breadcrumb">
        <Link href="/projects">Projects</Link> /{" "}
        <Link href={`/projects/${projectId}`}>{found.title}</Link>
      </p>
      <h1 className="page-title">Introductions to partners</h1>
      {sent ? (
        <FormNotice>
          Thanks. We&apos;re offering your request to checked partners in your area and will tell
          you when one accepts.
        </FormNotice>
      ) : null}
      {options && options.ok ? (
        <ReferralForm organisationId={orgId} projectId={projectId} options={options.data} />
      ) : options ? (
        <p className="muted">We couldn&apos;t load that assessment.</p>
      ) : null}
      {referrals.ok && referrals.data.length > 0 ? (
        <section className="panel" id="quotes" aria-labelledby="quotes-title">
          <h2 id="quotes-title" className="section-title">
            Quotes
          </h2>
          <CustomerQuotes
            organisationId={orgId}
            projectId={projectId}
            quotes={quotes.ok ? quotes.data : []}
            canWrite={canWrite}
          />
        </section>
      ) : null}
      <section className="panel" aria-labelledby="requests-title">
        <h2 id="requests-title" className="section-title">
          Your requests
        </h2>
        <ReferralList
          organisationId={orgId}
          projectId={projectId}
          referrals={referrals.ok ? referrals.data : []}
          canWrite={canWrite}
        />
      </section>
    </AppShell>
  );
}
