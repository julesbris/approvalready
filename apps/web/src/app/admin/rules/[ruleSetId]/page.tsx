import type { RuleSetOut } from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";

import { AdminNav } from "@/components/admin/AdminNav";
import { NewRuleForm, RuleSetScopeForm, verticalName } from "@/components/admin/RuleForms";
import { AppShell, NoAccess } from "@/components/app/AppShell";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = {
  title: "Rule set",
  robots: { index: false },
};

export default async function RuleSetPage({ params }: { params: Promise<{ ruleSetId: string }> }) {
  const { ruleSetId } = await params;
  const session = await requireSession(`/admin/rules/${ruleSetId}`);
  if (!session.permissions.includes("rule.author")) {
    return (
      <AppShell session={session}>
        <NoAccess what="rule authoring" />
      </AppShell>
    );
  }
  const ruleSet = orNotFound(
    await serverGet<RuleSetOut>(`/admin/rule-sets/${encodeURIComponent(ruleSetId)}`),
  );
  return (
    <AppShell session={session}>
      <AdminNav current="rules" />
      <section className="page-head">
        <div>
          <h1 className="page-title">{ruleSet.title}</h1>
          <p className="muted">
            {verticalName(ruleSet.vertical)} · {ruleSet.jurisdiction} · {ruleSet.key}
          </p>
        </div>
      </section>
      <section className="panel" aria-labelledby="rules-title">
        <h2 id="rules-title" className="section-title">
          Rules
        </h2>
        {ruleSet.rules.length === 0 ? (
          <p>No rules yet.</p>
        ) : (
          <ul className="card-list" aria-label="Rules">
            {ruleSet.rules.map((rule) => {
              const open = rule.draft_version_id ?? rule.published_version_id;
              return (
                <li key={rule.id} className="card">
                  {open ? (
                    <Link className="card-title" href={`/admin/rules/versions/${open}`}>
                      {rule.title}
                    </Link>
                  ) : (
                    <span className="card-title">{rule.title}</span>
                  )}
                  <div className="muted">
                    {rule.key} · latest version {rule.latest_version}
                    {rule.draft_version_id ? " (draft)" : ""}
                  </div>
                  <span className="status">
                    {rule.published_version !== null
                      ? `Published v${rule.published_version}`
                      : "Not published"}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </section>
      <section className="panel" aria-labelledby="new-rule-title">
        <h2 id="new-rule-title" className="section-title">
          Add a rule
        </h2>
        <NewRuleForm ruleSetId={ruleSet.id} />
      </section>
      <section className="panel" aria-labelledby="scope-title">
        <h2 id="scope-title" className="section-title">
          Rule set details
        </h2>
        <RuleSetScopeForm ruleSet={ruleSet} />
      </section>
    </AppShell>
  );
}
