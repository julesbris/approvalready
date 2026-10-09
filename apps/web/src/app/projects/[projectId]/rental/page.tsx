import type {
  ApplicationOut,
  InspectionOut,
  MaintenanceOut,
  ProjectDetailOut,
  RentalOut,
  TenancyOut,
} from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";

import { AppShell, NoAccess } from "@/components/app/AppShell";
import { RentalWorkspace } from "@/components/property/RentalWorkspace";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Your rental", robots: { index: false } };

type Props = { params: Promise<{ projectId: string }> };

export default async function RentalPage({ params }: Props) {
  const { projectId } = await params;
  const session = await requireSession(`/projects/${projectId}/rental`);
  const orgId = session.active_organisation_id;
  if (!orgId || !session.permissions.includes("project.read")) {
    return (
      <AppShell session={session}>
        <NoAccess what="projects" />
      </AppShell>
    );
  }
  const base = `/organisations/${orgId}/projects/${projectId}`;
  const [project, rental, applications, tenancies, inspections, maintenance] = await Promise.all([
    serverGet<ProjectDetailOut>(base),
    serverGet<RentalOut>(`${base}/rental`),
    serverGet<ApplicationOut[]>(`${base}/rental/applications`),
    serverGet<TenancyOut[]>(`${base}/rental/tenancies`),
    serverGet<InspectionOut[]>(`${base}/rental/inspections`),
    serverGet<MaintenanceOut[]>(`${base}/rental/maintenance`),
  ]);
  const found = orNotFound(project);
  return (
    <AppShell session={session}>
      <p className="breadcrumb">
        <Link href="/projects">Projects</Link> /{" "}
        <Link href={`/projects/${projectId}`}>{found.title}</Link>
      </p>
      {rental.ok ? (
        <RentalWorkspace
          organisationId={orgId}
          projectId={projectId}
          projectTitle={found.title}
          rental={rental.data}
          applications={applications.ok ? applications.data : []}
          tenancies={tenancies.ok ? tenancies.data : []}
          inspections={inspections.ok ? inspections.data : []}
          maintenance={maintenance.ok ? maintenance.data : []}
          canWrite={session.permissions.includes("project.write")}
        />
      ) : (
        <p>A rental belongs to a renting project.</p>
      )}
    </AppShell>
  );
}
