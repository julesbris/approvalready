import type { InspectionDetailOut, ProjectDetailOut } from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AppShell, NoAccess } from "@/components/app/AppShell";
import { InspectionRunner } from "@/components/property/InspectionRunner";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Inspection", robots: { index: false } };

type Props = { params: Promise<{ projectId: string; inspectionId: string }> };

export default async function InspectionPage({ params }: Props) {
  const { projectId, inspectionId } = await params;
  const session = await requireSession(`/projects/${projectId}/rental/inspections/${inspectionId}`);
  const orgId = session.active_organisation_id;
  if (!orgId || !session.permissions.includes("project.read")) {
    return (
      <AppShell session={session}>
        <NoAccess what="projects" />
      </AppShell>
    );
  }
  const org = `/organisations/${orgId}`;
  const [project, inspection] = await Promise.all([
    serverGet<ProjectDetailOut>(`${org}/projects/${projectId}`),
    serverGet<InspectionDetailOut>(`${org}/inspections/${inspectionId}`),
  ]);
  const found = orNotFound(project);
  const detail = orNotFound(inspection);
  if (detail.project_id !== projectId) notFound();
  return (
    <AppShell session={session}>
      <p className="breadcrumb">
        <Link href="/projects">Projects</Link> /{" "}
        <Link href={`/projects/${projectId}`}>{found.title}</Link> /{" "}
        <Link href={`/projects/${projectId}/rental`}>Rental</Link>
      </p>
      <InspectionRunner
        organisationId={orgId}
        projectId={projectId}
        inspection={detail}
        canWrite={session.permissions.includes("project.write")}
      />
    </AppShell>
  );
}
