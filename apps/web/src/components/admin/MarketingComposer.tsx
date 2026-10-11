"use client";

import type {
  MarketingChannel,
  MarketingChannelOut,
  MarketingGuideDraftsOut,
  MarketingGuideOut,
  MarketingPostOut,
} from "@approvalready/shared-types";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { useAction } from "@/components/admin/useAction";
import { FormError, FormNotice } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";
import { formatDate } from "@/lib/questionnaire";
import {
  CAPTION_LIMITS,
  CHANNELS,
  CHANNEL_LABELS,
  fromBrisbaneInput,
  toBrisbaneInput,
} from "@/lib/marketing";

type Draft = { on: boolean; subject: string; body: string };

/** Staff: pick a guide, edit the drafted post for each channel, then post now or schedule. */
export function MarketingComposer({
  guides,
  channels,
}: {
  guides: MarketingGuideOut[];
  channels: MarketingChannelOut[];
}) {
  const router = useRouter();
  const { busy, error, run, setError } = useAction();
  const [ref, setRef] = useState("");
  const [loaded, setLoaded] = useState<MarketingGuideDraftsOut | null>(null);
  const [drafts, setDrafts] = useState<Partial<Record<MarketingChannel, Draft>>>({});
  const [when, setWhen] = useState<"now" | "later">("now");
  const [at, setAt] = useState(() => toBrisbaneInput(new Date(Date.now() + 24 * 3600 * 1000)));
  const [done, setDone] = useState<string | null>(null);
  const ready = new Set(channels.filter((c) => c.configured).map((c) => c.channel));

  async function pick(next: string) {
    setRef(next);
    setLoaded(null);
    setDone(null);
    if (!next) return;
    const data = await run(() =>
      apiRequest<MarketingGuideDraftsOut>("GET", `/admin/marketing/guides/${next}/drafts`),
    );
    if (!data) return;
    setLoaded(data);
    setDrafts(
      Object.fromEntries(
        data.drafts.map((d) => [
          d.channel,
          { on: ready.has(d.channel), subject: d.subject ?? "", body: d.body },
        ]),
      ),
    );
  }

  function edit(channel: MarketingChannel, change: Partial<Draft>) {
    setDrafts((all) => ({ ...all, [channel]: { ...(all[channel] as Draft), ...change } }));
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const posts = CHANNELS.filter((c) => drafts[c]?.on).map((c) => ({
      channel: c,
      body: drafts[c]!.body,
      subject: c === "EMAIL" ? drafts[c]!.subject : null,
    }));
    if (posts.length === 0) {
      setError("Tick at least one channel.");
      return;
    }
    let scheduled: string | null = null;
    if (when === "later") {
      scheduled = fromBrisbaneInput(at);
      if (!scheduled) {
        setError("Choose a date and time.");
        return;
      }
    }
    const saved = await run(() =>
      apiRequest<MarketingPostOut[]>("POST", "/admin/marketing/posts", {
        guide_ref: ref,
        posts,
        scheduled_for: scheduled,
      }),
    );
    if (!saved) return;
    setDone(
      when === "now"
        ? "Posting now. It shows in the history below within a couple of minutes."
        : "Scheduled. It shows under Coming up below.",
    );
    setLoaded(null);
    setRef("");
    router.refresh();
  }

  return (
    <form method="post" className="form" onSubmit={onSubmit}>
      <label>
        Guide
        <select
          name="guide"
          value={ref}
          onChange={(e) => void pick(e.target.value)}
          disabled={busy}
        >
          <option value="">Choose a guide…</option>
          {guides.map((g) => (
            <option key={g.ref} value={g.ref}>
              {g.title} ({g.product})
              {g.last_posted_at ? `, last posted ${formatDate(g.last_posted_at.slice(0, 10))}` : ""}
            </option>
          ))}
        </select>
      </label>
      {done ? <FormNotice>{done}</FormNotice> : null}
      {loaded ? (
        <>
          <div className="marketing-preview">
            {/* eslint-disable-next-line @next/next/no-img-element -- generated card */}
            <img
              src={loaded.guide.card_path}
              alt={`Image card for ${loaded.guide.title}`}
              width={270}
              height={270}
            />
            <p className="form-aside">
              This image goes with the Facebook and Instagram posts. The email is text only.
            </p>
          </div>
          {CHANNELS.map((channel) => {
            const draft = drafts[channel];
            if (!draft) return null;
            const limit = CAPTION_LIMITS[channel];
            const setUp = ready.has(channel);
            return (
              <fieldset key={channel} className="marketing-channel">
                <legend>
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={draft.on}
                      disabled={!setUp}
                      onChange={(e) => edit(channel, { on: e.target.checked })}
                    />
                    {CHANNEL_LABELS[channel]}
                    {setUp ? "" : " (not set up yet)"}
                  </label>
                </legend>
                {channel === "EMAIL" ? (
                  <label>
                    Subject
                    <input
                      type="text"
                      maxLength={200}
                      value={draft.subject}
                      disabled={!draft.on}
                      onChange={(e) => edit(channel, { subject: e.target.value })}
                    />
                  </label>
                ) : null}
                <label>
                  {channel === "EMAIL" ? "Email text" : "Caption"}
                  <textarea
                    rows={channel === "EMAIL" ? 14 : 10}
                    maxLength={limit ?? 20000}
                    value={draft.body}
                    disabled={!draft.on}
                    onChange={(e) => edit(channel, { body: e.target.value })}
                  />
                  <span className="form-aside">
                    {draft.body.length}
                    {limit ? ` of ${limit}` : ""} characters
                    {channel === "EMAIL"
                      ? ". The unsubscribe link and who it's from are added to every email."
                      : ""}
                  </span>
                </label>
              </fieldset>
            );
          })}
          <fieldset className="marketing-channel">
            <legend>When</legend>
            <label className="checkbox-label">
              <input
                type="radio"
                name="when"
                checked={when === "now"}
                onChange={() => setWhen("now")}
              />
              Post now
            </label>
            <label className="checkbox-label">
              <input
                type="radio"
                name="when"
                checked={when === "later"}
                onChange={() => setWhen("later")}
              />
              Schedule for (Brisbane time)
            </label>
            {when === "later" ? (
              <input
                type="datetime-local"
                aria-label="Date and time, Brisbane time"
                value={at}
                onChange={(e) => setAt(e.target.value)}
              />
            ) : null}
          </fieldset>
          <FormError message={error} />
          <button type="submit" className="button" disabled={busy}>
            {when === "now" ? "Post now" : "Schedule"}
          </button>
        </>
      ) : (
        <FormError message={error} />
      )}
    </form>
  );
}
