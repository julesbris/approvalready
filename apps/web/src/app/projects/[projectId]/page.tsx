import type {
  MemberOut,
  ProjectDetailOut,
  PropertyOut,
  ReminderOut,
  TaskOut,
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
  const [project, tasks, reminders, members, properties] = await Promise.all([
    serverGet<ProjectDetailOut>(`${base}/projects/${projectId}`),
    serverGet<TaskOut[]>(`${base}/projects/${projectId}/tasks`),
    serverGet<ReminderOut[]>(`${base}/projects/${projectId}/reminders`),
    serverGet<MemberOut[]>(`${base}/members`),
    serverGet<PropertyOut[]>(`${base}/properties`),
  ]);
  return (
    <AppShell session={session}>
      <p className="breadcrumb">
        <Link href="/projects">Projects</Link>
      </p>
      <ProjectWorkspace
        organisationId={orgId}
        project={orNotFound(project)}
        tasks={orNotFound(tasks)}
        reminders={orNotFound(reminders)}
        members={members.ok ? members.data : []}
        properties={properties.ok ? properties.data : undefined}
        currentUserId={session.user.id}
        canWrite={session.permissions.includes("project.write")}
      />
    </AppShell>
  );
}
