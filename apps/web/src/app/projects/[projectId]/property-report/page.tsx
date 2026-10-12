import type { ProjectDetailOut } from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";

import { AppShell, NoAccess } from "@/components/app/AppShell";
import { PropertyReport } from "@/components/property/PropertyReport";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Property report", robots: { index: false } };

type Props = { params: Promise<{ projectId: string }> };

export default async function PropertyReportPage({ params }: Props) {
  const { projectId } = await params;
  const session = await requireSession(`/projects/${projectId}/property-report`);
  const orgId = session.active_organisation_id;
  if (!orgId || !session.permissions.includes("project.read")) {
    return (
      <AppShell session={session}>
        <NoAccess what="projects" />
      </AppShell>
    );
  }
  const project = orNotFound(
    await serverGet<ProjectDetailOut>(`/organisations/${orgId}/projects/${projectId}`),
  );
  return (
    <AppShell session={session}>
      <p className="breadcrumb">
        <Link href="/projects">Projects</Link> /{" "}
        <Link href={`/projects/${projectId}`}>{project.title}</Link>
      </p>
      <h1 className="page-title">Property report</h1>
      {project.property_id ? (
        <PropertyReport organisationId={orgId} propertyId={project.property_id} />
      ) : (
        <p>
          Add the property to <Link href={`/projects/${projectId}`}>the project</Link> first,
          then come back for its free report.
        </p>
      )}
    </AppShell>
  );
}
