import type {
  MarketingGuideOut,
  MarketingOverviewOut,
  MarketingPostOut,
} from "@approvalready/shared-types";
import type { Metadata } from "next";
import Link from "next/link";

import { AdminNav } from "@/components/admin/AdminNav";
import { MarketingAutopost } from "@/components/admin/MarketingAutopost";
import { MarketingComposer } from "@/components/admin/MarketingComposer";
import { MarketingPosts } from "@/components/admin/MarketingPosts";
import { AdminNoAccess, AppShell } from "@/components/app/AppShell";
import { CHANNEL_LABELS } from "@/lib/marketing";
import { orNotFound, requireSession, serverGet } from "@/lib/session";

export const metadata: Metadata = { title: "Marketing", robots: { index: false } };

export default async function MarketingPage() {
  const session = await requireSession("/admin/marketing");
  if (!session.permissions.includes("marketing.manage")) {
    return (
      <AppShell session={session}>
        <AdminNoAccess what="marketing" session={session} />
      </AppShell>
    );
  }
  const [overview, guides, posts] = await Promise.all([
    serverGet<MarketingOverviewOut>("/admin/marketing/overview"),
    serverGet<MarketingGuideOut[]>("/admin/marketing/guides"),
    serverGet<MarketingPostOut[]>("/admin/marketing/posts"),
  ]);
  const data = orNotFound(overview);
  const guideList = orNotFound(guides);
  return (
    <AppShell session={session}>
      <AdminNav current="marketing" />
      <h1 className="page-title">Marketing</h1>
      <p className="muted">
        Send our guides to Facebook, Instagram and the guides email list. Pick a guide and the posts
        are drafted for you with an image card; edit them, then post now or schedule. Or turn on
        auto-posting to send the next guide on set days.
      </p>

      <section className="panel" aria-labelledby="channels-title">
        <h2 id="channels-title" className="section-title">
          Channels
        </h2>
        <ul className="card-list" aria-label="Channels">
          {data.channels.map((c) => (
            <li key={c.channel} className="card">
              <strong>{CHANNEL_LABELS[c.channel]}</strong>{" "}
              <span
                className={`status ${c.configured && !c.error ? "status-active" : "status-pending"}`}
              >
                {!c.configured ? "Not set up" : c.error ? "Needs attention" : "Ready"}
              </span>
              <div className="muted">
                {!c.configured
                  ? "Add the Meta settings to the server to switch this on (see the deploy guide, Marketing)."
                  : c.error
                    ? c.error
                    : c.name
                      ? `Posts as ${c.name}.`
                      : ""}
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section className="panel" aria-labelledby="compose-title">
        <h2 id="compose-title" className="section-title">
          Post a guide
        </h2>
        <MarketingComposer guides={guideList} channels={data.channels} />
      </section>

      <section className="panel" aria-labelledby="autopost-title">
        <h2 id="autopost-title" className="section-title">
          Auto-posting
        </h2>
        <MarketingAutopost initial={data.autopost} guides={guideList} channels={data.channels} />
      </section>

      <section className="panel" aria-labelledby="list-title">
        <h2 id="list-title" className="section-title">
          Email list
        </h2>
        <p>
          {data.subscribers.subscribed} subscribed · {data.subscribers.pending} waiting to confirm ·{" "}
          {data.subscribers.unsubscribed} unsubscribed.{" "}
          <Link href="/admin/marketing/subscribers">See the list</Link>
        </p>
        <p className="muted">
          People join at <Link href="/newsletter">/newsletter</Link> (and confirm by email) or from
          their account. At most {data.newsletter_daily_limit} guide emails go out a day so sign-in
          emails always get through; bigger sends carry on the next day.
        </p>
      </section>

      <section className="panel" aria-labelledby="posts-title">
        <h2 id="posts-title" className="section-title">
          Posts
        </h2>
        <MarketingPosts posts={orNotFound(posts)} />
      </section>
    </AppShell>
  );
}
