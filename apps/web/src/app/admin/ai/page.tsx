import type { AIUsageOut, PromptVersionOut } from "@approvalready/shared-types";
import type { Metadata } from "next";

import { AdminNav } from "@/components/admin/AdminNav";
import { AIUsage } from "@/components/admin/AIUsage";
import { AppShell, NoAccess } from "@/components/app/AppShell";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "AI usage", robots: { index: false } };

export default async function AIAdminPage() {
  const session = await requireSession("/admin/ai");
  if (!session.permissions.includes("platform.audit.read")) {
    return (
      <AppShell session={session}>
        <NoAccess what="AI usage" />
      </AppShell>
    );
  }
  const [usage, prompts] = await Promise.all([
    serverGet<AIUsageOut>("/admin/ai/usage?days=30"),
    serverGet<PromptVersionOut[]>("/admin/ai/prompts"),
  ]);
  return (
    <AppShell session={session}>
      <AdminNav current="ai" />
      <h1 className="page-title">AI usage</h1>
      <p className="muted">
        AI only rewords findings and drafts notes from a project&apos;s own data. Every call is
        logged with its model, tokens and cost; drafts that name a finding, figure, date or link
        that is not in their input are rejected and never shown. Prompts change only through
        reviewed files in the repository.
      </p>
      <AIUsage usage={orNotFound(usage)} prompts={orNotFound(prompts)} />
    </AppShell>
  );
}
