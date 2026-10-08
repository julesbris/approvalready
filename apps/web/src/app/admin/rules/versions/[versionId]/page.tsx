import type {
  PublishChecksOut,
  RuleOut,
  RuleVersionOut,
  SourceReferenceOut,
} from "@approvalready/shared-types";
import type { Metadata } from "next";

import { AdminNav } from "@/components/admin/AdminNav";
import { RuleVersionEditor } from "@/components/admin/RuleVersionEditor";
import { AppShell, NoAccess } from "@/components/app/AppShell";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = {
  title: "Rule version",
  robots: { index: false },
};

export default async function RuleVersionPage({
  params,
}: {
  params: Promise<{ versionId: string }>;
}) {
  const { versionId } = await params;
  const session = await requireSession(`/admin/rules/versions/${versionId}`);
  if (!session.permissions.includes("rule.author")) {
    return (
      <AppShell session={session}>
        <NoAccess what="rule authoring" />
      </AppShell>
    );
  }
  const id = encodeURIComponent(versionId);
  const [version, checks, references] = await Promise.all([
    serverGet<RuleVersionOut>(`/admin/rule-versions/${id}`),
    serverGet<PublishChecksOut>(`/admin/rule-versions/${id}/checks`),
    serverGet<SourceReferenceOut[]>("/admin/source-references"),
  ]);
  const current = orNotFound(version);
  const rule = orNotFound(await serverGet<RuleOut>(`/admin/rules/${current.rule_id}`));
  return (
    <AppShell session={session}>
      <AdminNav current="rules" />
      <RuleVersionEditor
        key={`${current.id}-${current.updated_at}`}
        version={current}
        rule={rule}
        checks={orNotFound(checks)}
        references={orNotFound(references)}
        canPublish={session.permissions.includes("rule.publish")}
      />
    </AppShell>
  );
}
