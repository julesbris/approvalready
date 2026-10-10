import type { PartnerStatus, PartnerSummaryOut } from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";

import { AdminNav } from "@/components/admin/AdminNav";
import { AdminNoAccess, AppShell } from "@/components/app/AppShell";
import { PARTNER_STATUS_LABELS } from "@/lib/partners";
import { formatDate } from "@/lib/questionnaire";
import { firstParam } from "@/lib/redirect";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Partners", robots: { index: false } };

type Props = { searchParams: Promise<Record<string, string | string[] | undefined>> };

const FILTERS: [PartnerStatus | "", string][] = [
  ["", "All"],
  ["APPLIED", "New"],
  ["UNDER_REVIEW", "Being checked"],
  ["ACTIVE", "Approved"],
  ["SUSPENDED", "Suspended"],
  ["REJECTED", "Not approved"],
];

export default async function PartnersAdminPage({ searchParams }: Props) {
  const wanted = firstParam((await searchParams).status) ?? "";
  const status = FILTERS.some(([key]) => key === wanted) ? wanted : "";
  const session = await requireSession("/admin/partners");
  if (!session.permissions.includes("partner.verify")) {
    return (
      <AppShell session={session}>
        <AdminNoAccess what="partner checks" session={session} />
      </AppShell>
    );
  }
  const partners = orNotFound(
    await serverGet<PartnerSummaryOut[]>(`/admin/partners${status ? `?status=${status}` : ""}`),
  );
  return (
    <AppShell session={session}>
      <AdminNav current="partners" />
      <h1 className="page-title">Partners</h1>
      <p className="muted">
        Check each partner&apos;s ABN on the ABN Lookup, and each licence and insurance policy
        against the issuer&apos;s register, before approving their categories and the partner.
      </p>
      <nav aria-label="Filter partners" className="admin-nav">
        {FILTERS.map(([key, label]) => (
          <Link
            key={key || "all"}
            href={key ? `/admin/partners?status=${key}` : "/admin/partners"}
            aria-current={key === status ? "page" : undefined}
          >
            {label}
          </Link>
        ))}
      </nav>
      {partners.length === 0 ? (
        <section className="panel empty">
          <p>No partners here.</p>
        </section>
      ) : (
        <ul className="card-list" aria-label="Partners">
          {partners.map((p) => (
            <li key={p.id} className="card">
              <Link className="card-title" href={`/admin/partners/${p.id}`}>
                {p.name}
              </Link>
              <div className="muted">
                ABN {p.abn ?? "missing"} · {p.categories.join(", ") || "no categories"} · sent{" "}
                {formatDate(p.submitted_at)}
                {p.pending_categories > 0 ? ` · ${p.pending_categories} categories to check` : ""}
                {p.unchecked_credentials > 0
                  ? ` · ${p.unchecked_credentials} credentials to check`
                  : ""}
              </div>
              <span className="status">{PARTNER_STATUS_LABELS[p.status]}</span>
            </li>
          ))}
        </ul>
      )}
    </AppShell>
  );
}
