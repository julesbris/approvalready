"use client";

import type {
  MarketingAutopostOut,
  MarketingChannel,
  MarketingChannelOut,
  MarketingGuideOut,
} from "@approvalready/shared-types";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { useAction } from "@/components/admin/useAction";
import { FormError, FormNotice } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";
import { formatDate } from "@/lib/questionnaire";
import { CHANNELS, CHANNEL_LABELS, WEEKDAYS, timeInput } from "@/lib/marketing";

function toggle<T>(list: T[], item: T, on: boolean): T[] {
  return on ? [...new Set([...list, item])] : list.filter((x) => x !== item);
}

/** Staff: the auto-post schedule. On the chosen days and time it posts the next guide in the
 * rotation (the one posted longest ago) to each chosen channel. */
export function MarketingAutopost({
  initial,
  guides,
  channels,
}: {
  initial: MarketingAutopostOut;
  guides: MarketingGuideOut[];
  channels: MarketingChannelOut[];
}) {
  const router = useRouter();
  const { busy, error, run } = useAction();
  const [enabled, setEnabled] = useState(initial.enabled);
  const [picked, setPicked] = useState<MarketingChannel[]>(initial.channels);
  const [days, setDays] = useState<number[]>(initial.weekdays);
  const [at, setAt] = useState(timeInput(initial.post_at));
  const [skip, setSkip] = useState<string[]>(initial.skip_guides);
  const [saved, setSaved] = useState<MarketingAutopostOut | null>(null);
  const ready = new Set(channels.filter((c) => c.configured).map((c) => c.channel));
  const state = saved ?? initial;
  const next = guides.find((g) => g.ref === state.next_guide_ref);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const result = await run(() =>
      apiRequest<MarketingAutopostOut>("PUT", "/admin/marketing/autopost", {
        enabled,
        channels: picked,
        weekdays: days,
        post_at: at,
        skip_guides: skip,
      }),
    );
    if (result) {
      setSaved(result);
      router.refresh();
    }
  }

  return (
    <form method="post" className="form" onSubmit={onSubmit}>
      <label className="checkbox-label">
        <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
        Auto-post guides
      </label>
      <fieldset className="marketing-channel">
        <legend>Channels</legend>
        {CHANNELS.map((c) => (
          <label key={c} className="checkbox-label">
            <input
              type="checkbox"
              checked={picked.includes(c)}
              onChange={(e) => setPicked(toggle(picked, c, e.target.checked))}
            />
            {CHANNEL_LABELS[c]}
            {ready.has(c) ? "" : " (skipped until it's set up)"}
          </label>
        ))}
      </fieldset>
      <fieldset className="marketing-channel">
        <legend>Days</legend>
        <div className="button-row tight">
          {WEEKDAYS.map(([d, label]) => (
            <label key={d} className="checkbox-label">
              <input
                type="checkbox"
                checked={days.includes(d)}
                onChange={(e) => setDays(toggle(days, d, e.target.checked))}
              />
              {label}
            </label>
          ))}
        </div>
      </fieldset>
      <label>
        Time (Brisbane)
        <input type="time" value={at} required onChange={(e) => setAt(e.target.value)} />
      </label>
      <details>
        <summary>Guides to leave out ({skip.length})</summary>
        {guides.map((g) => (
          <label key={g.ref} className="checkbox-label">
            <input
              type="checkbox"
              checked={skip.includes(g.ref)}
              onChange={(e) => setSkip(toggle(skip, g.ref, e.target.checked))}
            />
            {g.title}
          </label>
        ))}
      </details>
      <p className="form-aside">
        {state.enabled && state.next_run
          ? `Next auto-post: ${formatDate(state.next_run)}${next ? `, "${next.title}"` : ""}. `
          : "Auto-posting is off. "}
        Posts go out as drafted; check the history below and cancel any you don&apos;t want before
        their time.
      </p>
      <FormError message={error} />
      {saved ? <FormNotice>Saved.</FormNotice> : null}
      <button type="submit" className="button" disabled={busy}>
        Save auto-posting
      </button>
    </form>
  );
}
