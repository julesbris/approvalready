import type { Metadata } from "next";

import { AppShell, NoAccess } from "@/components/app/AppShell";
import { NewProjectForm } from "@/components/projects/NewProjectForm";
import { isVertical } from "@/lib/labels";
import { firstParam } from "@/lib/redirect";
import { requireSession } from "@/lib/session";

export const metadata: Metadata = { title: "New project", robots: { index: false } };

type Props = { searchParams: Promise<Record<string, string | string[] | undefined>> };

export default async function NewProjectPage({ searchParams }: Props) {
  const session = await requireSession("/projects/new");
  const orgId = session.active_organisation_id;
  const vertical = firstParam((await searchParams).vertical);
  return (
    <AppShell session={session}>
      {orgId && session.permissions.includes("project.write") ? (
        <>
          <h1 className="page-title">New project</h1>
          <NewProjectForm
            organisationId={orgId}
            initialVertical={isVertical(vertical) ? vertical : null}
          />
        </>
      ) : (
        <NoAccess what="creating projects" />
      )}
    </AppShell>
  );
}
