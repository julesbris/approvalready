import type { ProjectOut } from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";

import { AppShell, NoAccess } from "@/components/app/AppShell";
import { formatDateTime, statusLabel, verticalName } from "@/lib/labels";
import { firstParam } from "@/lib/redirect";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Projects", robots: { index: false } };

type Props = { searchParams: Promise<Record<string, string | string[] | undefined>> };

export default async function ProjectsPage({ searchParams }: Props) {
  const session = await requireSession("/projects");
  const orgId = session.active_organisation_id;
  const showArchived = firstParam((await searchParams).archived) === "1";
  if (!orgId || !session.permissions.includes("project.read")) {
    return (
      <AppShell session={session}>
        <NoAccess what="projects" />
      </AppShell>
    );
  }
  const projects = orNotFound(
    await serverGet<ProjectOut[]>(
      `/organisations/${orgId}/projects${showArchived ? "?include_archived=true" : ""}`,
    ),
  );
  const canWrite = session.permissions.includes("project.write");
  return (
    <AppShell session={session}>
      <div className="page-head">
        <h1 className="page-title">Projects</h1>
        {canWrite ? (
          <Link className="button" href="/projects/new">
            New project
          </Link>
        ) : null}
      </div>
      {projects.length === 0 ? (
        <section className="panel empty">
          <p>
            {showArchived ? "No projects yet." : "No current projects."} A project holds
            everything about one approval question: your answers, tasks and reminders.
          </p>
          {canWrite ? <Link href="/projects/new">Start your first project</Link> : null}
        </section>
      ) : (
        <ul className="card-list" aria-label="Projects">
          {projects.map((project) => (
            <li key={project.id} className="card">
              <Link className="card-title" href={`/projects/${project.id}`}>
                {project.title}
              </Link>
              <div className="muted">
                {verticalName(project.vertical)} · {project.reference_code} · Updated{" "}
                {formatDateTime(project.updated_at)}
              </div>
              <span className={`status status-${project.status.toLowerCase()}`}>
                {statusLabel(project.status)}
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="form-aside">
        {showArchived ? (
          <Link href="/projects">Hide archived projects</Link>
        ) : (
          <Link href="/projects?archived=1">Show archived projects</Link>
        )}
      </p>
    </AppShell>
  );
}
