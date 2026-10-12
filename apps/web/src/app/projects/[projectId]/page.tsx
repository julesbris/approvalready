import type {
  BusinessProfileOut,
  ChecklistDefinitionOut,
  ChecklistOut,
  CouncilOut,
  DocumentOut,
  MemberOut,
  OfficialForm,
  ProjectDetailOut,
  ProjectPlanOut,
  PropertyOut,
  ReminderOut,
  SubmissionOut,
  TaskOut,
  VesselOut,
  WhatsLeftOut,
} from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";

import { AppShell, NoAccess } from "@/components/app/AppShell";
import { ProjectWorkspace } from "@/components/projects/ProjectWorkspace";
import { councilKey } from "@/lib/councils";
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
    whatsLeft,
    plan,
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
    serverGet<WhatsLeftOut>(`${base}/projects/${projectId}/whats-left`),
    serverGet<ProjectPlanOut>(`${base}/projects/${projectId}/plan`),
  ]);
  const found = orNotFound(project);
  const [definitions, forms] = await Promise.all([
    serverGet<ChecklistDefinitionOut[]>(`/checklists?vertical=${found.vertical}`),
    serverGet<OfficialForm[]>(`/guidance/forms?vertical=${found.vertical}`),
  ]);
  // Planning projects: how to apply to the council the latest answers name.
  const latest = [...found.submissions].sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0];
  let council: CouncilOut | undefined;
  if (found.vertical === "PLANNING" && latest) {
    const submission = await serverGet<SubmissionOut>(`${base}/submissions/${latest.id}`);
    const key = submission.ok ? councilKey(submission.data.answers["property.lga"]) : null;
    const councilResult = key ? await serverGet<CouncilOut>(`/councils/${key}`) : null;
    council = councilResult?.ok ? councilResult.data : undefined;
  }
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
        forms={forms.ok ? forms.data : []}
        documents={orNotFound(documents)}
        council={council}
        whatsLeft={whatsLeft.ok ? whatsLeft.data : undefined}
        plan={plan.ok ? plan.data : undefined}
        currentUserId={session.user.id}
        canWrite={session.permissions.includes("project.write")}
      />
    </AppShell>
  );
}
