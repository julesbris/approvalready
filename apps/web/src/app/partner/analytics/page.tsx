import type { BenchmarksOut, FunnelOut, PartnerAnalyticsOut } from "@approvalready/shared-types";
import type { Metadata } from "next";
import { redirect } from "next/navigation";

import {
  BenchmarkTable,
  FunnelTable,
  PeriodNav,
  Stats,
  partnerStats,
} from "@/components/analytics/Analytics";
import { NoAccess } from "@/components/app/AppShell";
import { PartnerShell } from "@/components/partners/PartnerShell";
import { PERIOD_LABELS, monthLabel, parsePeriod } from "@/lib/analytics";
import { activePartnerOrganisation } from "@/lib/partners";
import { firstParam } from "@/lib/redirect";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = {
  title: "Insights",
  robots: { index: false },
};

type Props = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function PartnerAnalyticsPage({ searchParams }: Props) {
  const months = parsePeriod(firstParam((await searchParams).months));
  const session = await requireSession("/partner/analytics");
  const active = activePartnerOrganisation(session);
  if (!active) redirect("/partner");
  if (!session.permissions.includes("lead.read")) {
    return (
      <PartnerShell session={session} current="analytics">
        <NoAccess what="insights" />
      </PartnerShell>
    );
  }
  const base = `/organisations/${active.organisation_id}/partner`;
  const [reportRes, benchRes] = await Promise.all([
    serverGet<PartnerAnalyticsOut>(`${base}/analytics?months=${months}`),
    serverGet<BenchmarksOut>(`${base}/benchmarks?months=${months}`),
  ]);
  const report = orNotFound(reportRes);
  const bench = orNotFound(benchRes);
  const mine = new Map<string, FunnelOut>([["", report.totals]]);
  for (const row of report.by_category) mine.set(row.category_key, row);
  return (
    <PartnerShell session={session} current="analytics">
      <h1 className="page-title">Insights</h1>
      <p className="muted">
        How your referrals went: offered, accepted, won, how quickly you replied and what you paid.
        These are your own figures. Customers&apos; details never appear here.
      </p>
      <PeriodNav path="/partner/analytics" current={months} />

      <section className="panel" aria-labelledby="summary-title">
        <h2 id="summary-title" className="section-title">
          {PERIOD_LABELS[months]}
        </h2>
        <Stats items={partnerStats(report.totals)} />
        <p className="muted">
          Missed means the referral closed before you replied. Replying sooner, even to decline,
          improves your place in future matches.
        </p>
      </section>

      <section className="panel" aria-labelledby="bench-title">
        <h2 id="bench-title" className="section-title">
          Compared with other partners
        </h2>
        <BenchmarkTable mine={mine} bench={bench} />
      </section>

      <section className="panel" aria-labelledby="category-title">
        <h2 id="category-title" className="section-title">
          By category
        </h2>
        <FunnelTable
          rows={report.by_category}
          heading="Category"
          label={(r) => r.category_label}
          caption="Your referrals by category"
        />
      </section>

      <section className="panel" aria-labelledby="area-title">
        <h2 id="area-title" className="section-title">
          By area
        </h2>
        <FunnelTable
          rows={report.by_area}
          heading="Area"
          label={(r) => `${r.area} ${r.state}`}
          caption="Your referrals by area"
        />
      </section>

      <section className="panel" aria-labelledby="month-title">
        <h2 id="month-title" className="section-title">
          By month
        </h2>
        <FunnelTable
          rows={report.by_month}
          heading="Month"
          label={(r) => monthLabel(r.month)}
          caption="Your referrals by month"
        />
      </section>
    </PartnerShell>
  );
}
