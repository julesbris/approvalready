import type { ProjectDetailOut, SmsOut } from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";

import { AppShell, NoAccess } from "@/components/app/AppShell";
import { SmsBuilder } from "@/components/vessels/SmsBuilder";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = {
  title: "Safety management system",
  robots: { index: false },
};

type Props = { params: Promise<{ projectId: string }> };

export default async function SmsPage({ params }: Props) {
  const { projectId } = await params;
  const session = await requireSession(`/projects/${projectId}/sms`);
  const orgId = session.active_organisation_id;
  if (!orgId || !session.permissions.includes("project.read")) {
    return (
      <AppShell session={session}>
        <NoAccess what="projects" />
      </AppShell>
    );
  }
  const base = `/organisations/${orgId}`;
  const [project, sms] = await Promise.all([
    serverGet<ProjectDetailOut>(`${base}/projects/${projectId}`),
    serverGet<SmsOut>(`${base}/projects/${projectId}/sms`),
  ]);
  const found = orNotFound(project);
  return (
    <AppShell session={session}>
      <p className="breadcrumb">
        <Link href="/projects">Projects</Link> /{" "}
        <Link href={`/projects/${projectId}`}>{found.title}</Link>
      </p>
      {sms.ok ? (
        <SmsBuilder
          organisationId={orgId}
          projectId={projectId}
          latestAssessmentId={found.latest_assessment?.id ?? null}
          sms={sms.data}
          canWrite={session.permissions.includes("project.write")}
        />
      ) : (
        <p>A safety management system belongs to a vessel project.</p>
      )}
    </AppShell>
  );
}
