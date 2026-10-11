import type { NewsletterSubscriberOut } from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";

import { AdminNav } from "@/components/admin/AdminNav";
import { SubscriberList } from "@/components/admin/SubscriberList";
import { AdminNoAccess, AppShell } from "@/components/app/AppShell";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Email list", robots: { index: false } };

export default async function SubscribersPage() {
  const session = await requireSession("/admin/marketing/subscribers");
  if (!session.permissions.includes("marketing.manage")) {
    return (
      <AppShell session={session}>
        <AdminNoAccess what="the email list" session={session} />
      </AppShell>
    );
  }
  const rows = orNotFound(
    await serverGet<NewsletterSubscriberOut[]>("/admin/marketing/subscribers"),
  );
  return (
    <AppShell session={session}>
      <AdminNav current="marketing" />
      <p>
        <Link href="/admin/marketing">Back to marketing</Link>
      </p>
      <h1 className="page-title">Email list</h1>
      <p className="muted">
        Everyone who joined the guides email list, newest first. People who sign up on the form show
        as waiting until they confirm by email; unconfirmed sign-ups are deleted after 30 days.
      </p>
      <SubscriberList initial={rows} />
    </AppShell>
  );
}
