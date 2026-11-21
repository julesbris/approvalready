"use client";

import type { JourneyOut, RsMemberOut, RsVehicleOut } from "@approvalready/shared-types";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { FormError } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";
import {
  REMOTENESS_LABELS,
  formatContacts,
  parseContacts,
  toLocalInput,
} from "@/lib/remotesafe";

type Props = {
  base: string;
  members: RsMemberOut[];
  vehicles: RsVehicleOut[];
  timezones: Record<string, string>;
  defaultTimezone: string;
  meId: string;
  canPlanForOthers: boolean;
  journey?: JourneyOut;
  onSaved?: (journey: JourneyOut) => void;
};

function text(form: FormData, name: string): string | null {
  return String(form.get(name) ?? "").trim() || null;
}

/** The journey's details: people, places, times, vehicle and communications. */
export function JourneyForm({ journey, base, members, vehicles, timezones, ...props }: Props) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const zone = journey?.timezone ?? props.defaultTimezone;
  const has = (m: RsMemberOut, roles: string[]) => m.roles.some((r) => roles.includes(r));
  const workers = members.filter((m) => has(m, ["WORKER", "SUPERVISOR", "WHS_ADMIN"]));
  const supervisors = members.filter((m) => has(m, ["SUPERVISOR", "WHS_ADMIN"]));
  const monitors = members.filter((m) => has(m, ["MONITOR", "SUPERVISOR", "WHS_ADMIN"]));
  const local = (v: { utc: string } | null | undefined) => (v ? toLocalInput(v.utc, zone) : "");

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const contacts = parseContacts(String(form.get("contacts") ?? ""));
    if ("error" in contacts) {
      setError(contacts.error);
      return;
    }
    const vehicleId = text(form, "vehicle_id");
    const interval = text(form, "checkin_interval_minutes");
    const body: Record<string, unknown> = {
      title: text(form, "title"),
      purpose: text(form, "purpose"),
      activities: text(form, "activities"),
      supervisor_user_id: text(form, "supervisor_user_id"),
      monitor_user_id: text(form, "monitor_user_id"),
      team: text(form, "team"),
      worker_phone: text(form, "worker_phone"),
      origin: text(form, "origin"),
      destination: text(form, "destination"),
      remoteness: text(form, "remoteness"),
      return_journey: form.get("return_journey") === "on",
      timezone: text(form, "timezone"),
      departs_at: text(form, "departs_at"),
      arrives_at: text(form, "arrives_at"),
      returns_at: text(form, "returns_at"),
      vehicle_id: vehicleId,
      vehicle_description: vehicleId
        ? (vehicles.find((v) => v.id === vehicleId)?.name ?? null)
        : text(form, "vehicle_description"),
      vehicle_registration: vehicleId
        ? (vehicles.find((v) => v.id === vehicleId)?.registration ?? null)
        : text(form, "vehicle_registration"),
      occupants: Number(text(form, "occupants") ?? 1),
      comms_mobile: form.get("comms_mobile") === "on",
      comms_uhf: form.get("comms_uhf") === "on",
      comms_sat_phone: form.get("comms_sat_phone") === "on",
      comms_sat_messenger: form.get("comms_sat_messenger") === "on",
      comms_notes: text(form, "comms_notes"),
      emergency_contacts: contacts.map((c, i) => ({
        name: c.name,
        relationship: c.relationship || null,
        phone: c.phone,
        escalation_order: i + 1,
      })),
      checkin_interval_minutes: interval ? Number(interval) : null,
      alternative_route: text(form, "alternative_route"),
      contingency_plan: text(form, "contingency_plan"),
      weather_checked_at: text(form, "weather_checked_at"),
      weather_source: text(form, "weather_source"),
      weather_warnings: text(form, "weather_warnings"),
    };
    if (!journey) body.worker_user_id = text(form, "worker_user_id") ?? props.meId;
    setBusy(true);
    setError(null);
    const result = journey
      ? await apiRequest<JourneyOut>("PATCH", `${base}/journeys/${journey.id}`, body)
      : await apiRequest<JourneyOut>("POST", `${base}/journeys`, body);
    setBusy(false);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    if (journey) props.onSaved?.(result.data);
    else router.push(`/remotesafe/journeys/${result.data.id}`);
  }

  return (
    <form method="post" className="form" onSubmit={save} aria-label="Journey details">
      <FormError message={error} />
      <h3 className="subsection-title">Who and why</h3>
      <label>
        Journey name
        <input name="title" required maxLength={200} defaultValue={journey?.title ?? ""} />
      </label>
      <label>
        Purpose of travel
        <textarea name="purpose" required maxLength={1000} defaultValue={journey?.purpose ?? ""} />
      </label>
      <label>
        Work to be done (optional)
        <textarea name="activities" maxLength={2000} defaultValue={journey?.activities ?? ""} />
      </label>
      <div className="field-row">
        {!journey && props.canPlanForOthers ? (
          <label>
            Worker
            <select name="worker_user_id" defaultValue={props.meId}>
              {workers.map((m) => (
                <option key={m.user_id} value={m.user_id}>
                  {m.display_name}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <label>
          Supervisor (approves)
          <select name="supervisor_user_id" defaultValue={journey?.supervisor?.user_id ?? ""}>
            <option value="">Choose later</option>
            {supervisors
              .filter((m) => m.user_id !== (journey?.worker.user_id ?? props.meId))
              .map((m) => (
                <option key={m.user_id} value={m.user_id}>
                  {m.display_name}
                </option>
              ))}
          </select>
        </label>
        <label>
          Journey monitor
          <select name="monitor_user_id" defaultValue={journey?.monitor?.user_id ?? ""}>
            <option value="">Choose later</option>
            {monitors
              .filter((m) => m.user_id !== (journey?.worker.user_id ?? props.meId))
              .map((m) => (
                <option key={m.user_id} value={m.user_id}>
                  {m.display_name}
                </option>
              ))}
          </select>
        </label>
      </div>
      <div className="field-row">
        <label>
          Team (optional)
          <input name="team" maxLength={120} defaultValue={journey?.team ?? ""} />
        </label>
        <label>
          Worker&apos;s mobile
          <input name="worker_phone" maxLength={40} defaultValue={journey?.worker_phone ?? ""} />
        </label>
      </div>

      <h3 className="subsection-title">Where and when</h3>
      <div className="field-row">
        <label>
          Leaving from
          <input name="origin" required maxLength={200} defaultValue={journey?.origin ?? ""} />
        </label>
        <label>
          Going to
          <input
            name="destination"
            required
            maxLength={200}
            defaultValue={journey?.destination ?? ""}
          />
        </label>
      </div>
      <div className="field-row">
        <label>
          How remote is the route?
          <select name="remoteness" defaultValue={journey?.remoteness ?? "UNKNOWN"}>
            {Object.entries(REMOTENESS_LABELS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label>
          Time zone for these times
          <select name="timezone" defaultValue={zone}>
            {Object.entries(timezones).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="field-row">
        <label>
          Departs
          <input
            name="departs_at"
            type="datetime-local"
            required
            defaultValue={local(journey?.departs)}
          />
        </label>
        <label>
          Expected arrival
          <input
            name="arrives_at"
            type="datetime-local"
            required
            defaultValue={local(journey?.arrives)}
          />
        </label>
        <label>
          Expected return (optional)
          <input name="returns_at" type="datetime-local" defaultValue={local(journey?.returns)} />
        </label>
      </div>
      <label className="option">
        <input
          type="checkbox"
          name="return_journey"
          defaultChecked={journey?.return_journey ?? false}
        />{" "}
        This plan includes the return trip
      </label>

      <h3 className="subsection-title">Vehicle</h3>
      <div className="field-row">
        <label>
          Fleet vehicle
          <select name="vehicle_id" defaultValue={journey?.vehicle_id ?? ""}>
            <option value="">Not a fleet vehicle</option>
            {vehicles
              .filter((v) => v.active || v.id === journey?.vehicle_id)
              .map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name} ({v.registration})
                </option>
              ))}
          </select>
        </label>
        <label>
          Or describe it
          <input
            name="vehicle_description"
            maxLength={200}
            defaultValue={journey?.vehicle_id ? "" : (journey?.vehicle_description ?? "")}
          />
        </label>
        <label>
          Registration
          <input
            name="vehicle_registration"
            maxLength={20}
            defaultValue={journey?.vehicle_id ? "" : (journey?.vehicle_registration ?? "")}
          />
        </label>
        <label>
          People on board
          <input
            name="occupants"
            type="number"
            min={1}
            max={60}
            defaultValue={journey?.occupants ?? 1}
          />
        </label>
      </div>

      <h3 className="subsection-title">Communications and emergencies</h3>
      <fieldset className="options">
        <legend>Carried on this trip</legend>
        <label className="option">
          <input type="checkbox" name="comms_mobile" defaultChecked={journey?.comms_mobile ?? true} />{" "}
          Mobile phone
        </label>
        <label className="option">
          <input type="checkbox" name="comms_uhf" defaultChecked={journey?.comms_uhf ?? false} /> UHF
          radio
        </label>
        <label className="option">
          <input
            type="checkbox"
            name="comms_sat_phone"
            defaultChecked={journey?.comms_sat_phone ?? false}
          />{" "}
          Satellite phone
        </label>
        <label className="option">
          <input
            type="checkbox"
            name="comms_sat_messenger"
            defaultChecked={journey?.comms_sat_messenger ?? false}
          />{" "}
          Satellite messenger (e.g. inReach)
        </label>
      </fieldset>
      <label>
        Communications notes (optional)
        <input name="comms_notes" maxLength={1000} defaultValue={journey?.comms_notes ?? ""} />
      </label>
      <label>
        Emergency contacts, in the order to call them
        <textarea
          name="contacts"
          rows={3}
          placeholder={"Depot, base, 07 4000 0000\nArea manager, 0411 111 111"}
          defaultValue={formatContacts(journey?.emergency_contacts ?? [])}
        />
        <span className="hint">One per line: name, relationship (optional), phone.</span>
      </label>
      <label>
        Check in every (minutes)
        <input
          name="checkin_interval_minutes"
          type="number"
          min={15}
          max={1440}
          defaultValue={journey?.checkin_interval_minutes ?? 120}
        />
      </label>
      <div className="field-row">
        <label>
          Alternative route (optional)
          <textarea
            name="alternative_route"
            maxLength={2000}
            defaultValue={journey?.alternative_route ?? ""}
          />
        </label>
        <label>
          If something goes wrong (optional)
          <textarea
            name="contingency_plan"
            maxLength={2000}
            defaultValue={journey?.contingency_plan ?? ""}
          />
        </label>
      </div>

      <h3 className="subsection-title">Weather check</h3>
      <p className="hint">
        RemoteSafe doesn&apos;t look up weather yet. Check the Bureau of Meteorology warnings for
        your route and record what you found.
      </p>
      <div className="field-row">
        <label>
          Checked at
          <input
            name="weather_checked_at"
            type="datetime-local"
            defaultValue={
              journey?.weather_checked_at ? toLocalInput(journey.weather_checked_at, zone) : ""
            }
          />
        </label>
        <label>
          Where you checked
          <input
            name="weather_source"
            maxLength={200}
            placeholder="Bureau of Meteorology warnings"
            defaultValue={journey?.weather_source ?? ""}
          />
        </label>
      </div>
      <label>
        Warnings in effect (leave empty if none)
        <input
          name="weather_warnings"
          maxLength={1000}
          defaultValue={journey?.weather_warnings ?? ""}
        />
      </label>
      <div className="button-row">
        <button type="submit" className="button" disabled={busy}>
          {journey ? "Save changes" : "Create journey"}
        </button>
      </div>
    </form>
  );
}
