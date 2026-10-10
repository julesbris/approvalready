import type { RuleSetOut } from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";

import { AdminNav } from "@/components/admin/AdminNav";
import { NewRuleSetForm, verticalName } from "@/components/admin/RuleForms";
import { AdminNoAccess, AppShell } from "@/components/app/AppShell";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Rules", robots: { index: false } };

export default async function RulesPage() {
  const session = await requireSession("/admin/rules");
  if (!session.permissions.includes("rule.author")) {
    return (
      <AppShell session={session}>
        <AdminNoAccess what="rule authoring" session={session} />
      </AppShell>
    );
  }
  const ruleSets = orNotFound(await serverGet<RuleSetOut[]>("/admin/rule-sets"));
  return (
    <AppShell session={session}>
      <AdminNav current="rules" />
      <h1 className="page-title">Rules</h1>
      <p className="muted">
        Rules are versioned. Assessments use the version published and in force on the assessment
        date, and keep a record of exactly which version they used.
      </p>
      {ruleSets.length === 0 ? (
        <section className="panel empty">
          <p>No rule sets yet.</p>
        </section>
      ) : (
        <ul className="card-list" aria-label="Rule sets">
          {ruleSets.map((rs) => {
            const published = rs.rules.filter((r) => r.published_version !== null).length;
            return (
              <li key={rs.id} className="card">
                <Link className="card-title" href={`/admin/rules/${rs.id}`}>
                  {rs.title}
                </Link>
                <div className="muted">
                  {verticalName(rs.vertical)} · {rs.jurisdiction} · {rs.rules.length} rule(s),{" "}
                  {published} published
                </div>
                <span className="status">{rs.key}</span>
              </li>
            );
          })}
        </ul>
      )}
      <section className="panel" aria-labelledby="new-set-title">
        <h2 id="new-set-title" className="section-title">
          Add a rule set
        </h2>
        <NewRuleSetForm />
      </section>
    </AppShell>
  );
}
