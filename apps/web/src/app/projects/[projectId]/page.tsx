import type {
  BusinessProfileOut,
  ChecklistDefinitionOut,
  ChecklistOut,
  DocumentOut,
  MemberOut,
  ProjectDetailOut,
  PropertyOut,
  ReminderOut,
  TaskOut,
  VesselOut,
} from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";

import { AppShell, NoAccess } from "@/components/app/AppShell";
import { ProjectWorkspace } from "@/components/projects/ProjectWorkspace";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Project", robots: { index: false } };

type Props = { params: Promise<{ projectId: string }> };

export default async function ProjectPage({ params }: Props) {
  const { projectId } = await params;
  const session = await requireSession(`/projects/${projectId}`);
  const orgId = session.active_organisation_id;
  if (!orgId || !session.permissions.includes("project.read")) {
    return (
      <AppShell session={session}>
        <NoAccess what="projects" />
      </AppShell>
    );
  }
  const base = `/organisations/${orgId}`;
  const [
    project,
    tasks,
    reminders,
    members,
    properties,
    documents,
    businesses,
    vessels,
    checklists,
  ] = await Promise.all([
    serverGet<ProjectDetailOut>(`${base}/projects/${projectId}`),
    serverGet<TaskOut[]>(`${base}/projects/${projectId}/tasks`),
    serverGet<ReminderOut[]>(`${base}/projects/${projectId}/reminders`),
    serverGet<MemberOut[]>(`${base}/members`),
    serverGet<PropertyOut[]>(`${base}/properties`),
    serverGet<DocumentOut[]>(`${base}/projects/${projectId}/documents`),
    serverGet<BusinessProfileOut[]>(`${base}/business-profiles`),
    serverGet<VesselOut[]>(`${base}/vessels`),
    serverGet<ChecklistOut[]>(`${base}/projects/${projectId}/checklists`),
  ]);
  const found = orNotFound(project);
  const definitions = await serverGet<ChecklistDefinitionOut[]>(
    `/checklists?vertical=${found.vertical}`,
  );
  return (
    <AppShell session={session}>
      <p className="breadcrumb">
        <Link href="/projects">Projects</Link>
      </p>
      <ProjectWorkspace
        organisationId={orgId}
        project={found}
        tasks={orNotFound(tasks)}
        reminders={orNotFound(reminders)}
        members={members.ok ? members.data : []}
        properties={properties.ok ? properties.data : undefined}
        businesses={businesses.ok ? businesses.data : undefined}
        vessels={vessels.ok ? vessels.data : undefined}
        checklists={checklists.ok ? checklists.data : undefined}
        checklistDefinitions={definitions.ok ? definitions.data : []}
        documents={orNotFound(documents)}
        currentUserId={session.user.id}
        canWrite={session.permissions.includes("project.write")}
      />
    </AppShell>
  );
}
