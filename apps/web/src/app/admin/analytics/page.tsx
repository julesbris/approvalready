import type { MarketplaceAnalyticsOut } from "@approvalready/shared-types";
import type { Metadata } from "next";

import { AdminNav } from "@/components/admin/AdminNav";
import {
  MarketPartners,
  MarketTable,
  PeriodNav,
  Stats,
  marketStats,
} from "@/components/analytics/Analytics";
import { AdminNoAccess, AppShell } from "@/components/app/AppShell";
import { PERIOD_LABELS, monthLabel, parsePeriod } from "@/lib/analytics";
import { firstParam } from "@/lib/redirect";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = {
  title: "Marketplace",
  robots: { index: false },
};

type Props = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function MarketplaceAnalyticsPage({ searchParams }: Props) {
  const months = parsePeriod(firstParam((await searchParams).months));
  const session = await requireSession("/admin/analytics");
  if (!session.permissions.includes("lead.manage")) {
    return (
      <AppShell session={session}>
        <AdminNav current="analytics" />
        <AdminNoAccess what="marketplace figures" session={session} />
      </AppShell>
    );
  }
  const report = orNotFound(
    await serverGet<MarketplaceAnalyticsOut>(`/admin/analytics/marketplace?months=${months}`),
  );
  return (
    <AppShell session={session}>
      <AdminNav current="analytics" />
      <h1 className="page-title">Marketplace</h1>
      <p className="muted">
        Introduction requests (one per category a customer asked for) and how partners answered
        them. Counts only: no customer details. &quot;No partner available&quot; means matching
        found nobody eligible, so it shows where more partners are needed.
      </p>
      <PeriodNav path="/admin/analytics" current={months} />

      <section className="panel" aria-labelledby="summary-title">
        <h2 id="summary-title" className="section-title">
          {PERIOD_LABELS[months]}
        </h2>
        <Stats items={marketStats(report.totals)} />
      </section>

      <section className="panel" aria-labelledby="category-title">
        <h2 id="category-title" className="section-title">
          By category
        </h2>
        <MarketTable
          rows={report.by_category}
          heading="Category"
          label={(r) => r.category_label}
          caption="Requests by category"
        />
      </section>

      <section className="panel" aria-labelledby="area-title">
        <h2 id="area-title" className="section-title">
          By area
        </h2>
        <MarketTable
          rows={report.by_area}
          heading="Area"
          label={(r) => `${r.area} ${r.state}`}
          caption="Requests by area"
        />
      </section>

      <section className="panel" aria-labelledby="month-title">
        <h2 id="month-title" className="section-title">
          By month
        </h2>
        <MarketTable
          rows={report.by_month}
          heading="Month"
          label={(r) => monthLabel(r.month)}
          caption="Requests by month"
        />
      </section>

      <section className="panel" aria-labelledby="partners-title">
        <h2 id="partners-title" className="section-title">
          Partners
        </h2>
        <p className="muted">The 50 partners offered the most referrals in this period.</p>
        <MarketPartners partners={report.partners} />
      </section>
    </AppShell>
  );
}
