"use client";

import type { RiskPolicyOut, RsMemberOut, RsVehicleOut } from "@approvalready/shared-types";
import { type FormEvent, useState } from "react";

import { FormError } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";
import { ROLE_LABELS } from "@/lib/remotesafe";

type Props = {
  base: string;
  canManageRoles: boolean;
  tier: string;
  members: RsMemberOut[];
  vehicles: RsVehicleOut[];
  policy: RiskPolicyOut;
};

type HazardRow = {
  key: string;
  title: string;
  likelihood: number;
  consequence: number;
  residual_likelihood: number;
};

/** RemoteSafe settings: who does what, the vehicle register and the risk policy. */
export function RemoteSafeAdmin({ base, canManageRoles, tier, ...props }: Props) {
  const [members, setMembers] = useState(props.members);
  const [vehicles, setVehicles] = useState(props.vehicles);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const hazards = (props.policy.effective.hazards ?? []) as HazardRow[];
  const bands = props.policy.effective.rating_bands as Record<string, number>;

  async function toggleRole(member: RsMemberOut, role: string) {
    const roles = member.roles.includes(role)
      ? member.roles.filter((r) => r !== role)
      : [...member.roles, role];
    setBusy(true);
    setError(null);
    const r = await apiRequest<null>("PUT", `${base}/members/${member.user_id}/roles`, { roles });
    setBusy(false);
    if (!r.ok) {
      setError(r.message);
      return;
    }
    setMembers((all) => all.map((m) => (m.user_id === member.user_id ? { ...m, roles } : m)));
  }

  async function addVehicle(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const range = String(form.get("fuel_range_km") ?? "").trim();
    setBusy(true);
    setError(null);
    const r = await apiRequest<RsVehicleOut>("POST", `${base}/vehicles`, {
      name: String(form.get("name") ?? "").trim(),
      registration: String(form.get("registration") ?? "").trim(),
      vehicle_type: String(form.get("vehicle_type") ?? "").trim(),
      fuel_range_km: range ? Number(range) : null,
    });
    setBusy(false);
    if (!r.ok) {
      setError(r.message);
      return;
    }
    setVehicles((all) => [...all, r.data]);
    formElement.reset();
  }

  async function retire(v: RsVehicleOut) {
    const r = await apiRequest<RsVehicleOut>("PUT", `${base}/vehicles/${v.id}`, {
      ...v,
      active: !v.active,
    });
    if (r.ok) setVehicles((all) => all.map((x) => (x.id === v.id ? r.data : x)));
    else setError(r.message);
  }

  async function savePolicy(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const overrides: Record<string, unknown> = { ...props.policy.overrides };
    const changed: Record<string, Record<string, number>> = {};
    for (const h of hazards) {
      const l = Number(form.get(`${h.key}.likelihood`));
      const c = Number(form.get(`${h.key}.consequence`));
      const rl = Number(form.get(`${h.key}.residual_likelihood`));
      if (l !== h.likelihood || c !== h.consequence || rl !== h.residual_likelihood) {
        changed[h.key] = { likelihood: l, consequence: c, residual_likelihood: rl };
      }
    }
    overrides.hazards = { ...((overrides.hazards as object) ?? {}), ...changed };
    setBusy(true);
    setError(null);
    const r = await apiRequest<RiskPolicyOut>("PUT", `${base}/policy`, { overrides });
    setBusy(false);
    if (!r.ok) setError(r.message);
    else setSaved(`Saved as policy version ${r.data.policy_version}.`);
  }

  return (
    <div className="workspace">
      <FormError message={error} />
      {saved ? (
        <p className="notice" role="status">
          {saved}
        </p>
      ) : null}
      <section className="panel" aria-label="People">
        <h2 className="section-title">People and roles</h2>
        <p className="hint">
          Workers plan their own journeys. Supervisors plan for others and approve. Journey
          monitors see the journeys they monitor. WHS administrators see every journey, approve
          high-risk journeys, record exceptions and set the risk policy.
        </p>
        <ul className="task-list">
          {members.map((m) => (
            <li key={m.user_id} className="task">
              <div>
                <strong>{m.display_name}</strong> <span className="muted">{m.email}</span>
              </div>
              <div className="options">
                {Object.entries(ROLE_LABELS).map(([role, name]) => (
                  <label key={role} className="option">
                    <input
                      type="checkbox"
                      checked={m.roles.includes(role)}
                      disabled={!canManageRoles || busy}
                      onChange={() => toggleRole(m, role)}
                    />{" "}
                    {name}
                  </label>
                ))}
              </div>
            </li>
          ))}
        </ul>
        <p className="hint">
          To add someone, invite them to the organisation under Account, then give them a role
          here.
        </p>
      </section>

      <section className="panel" aria-label="Vehicles">
        <h2 className="section-title">Vehicle register</h2>
        <ul className="task-list">
          {vehicles.map((v) => (
            <li key={v.id} className="task">
              <div>
                <strong>{v.name}</strong> ({v.registration}) · {v.vehicle_type}
                {v.fuel_range_km ? ` · range ${v.fuel_range_km} km` : " · range not recorded"}
                {v.active ? "" : " · retired"}
              </div>
              <button type="button" className="button-link" onClick={() => retire(v)}>
                {v.active ? "Retire" : "Bring back"}
              </button>
            </li>
          ))}
        </ul>
        <form method="post" className="form" onSubmit={addVehicle} aria-label="Add a vehicle">
          <div className="field-row">
            <label>
              Name
              <input name="name" required maxLength={120} placeholder="LandCruiser 3" />
            </label>
            <label>
              Registration
              <input name="registration" required maxLength={20} />
            </label>
            <label>
              Type
              <input name="vehicle_type" required maxLength={60} placeholder="4WD wagon" />
            </label>
            <label>
              Fuel range (km)
              <input name="fuel_range_km" type="number" min={1} max={5000} />
            </label>
          </div>
          <button type="submit" className="button button-secondary" disabled={busy}>
            Add vehicle
          </button>
        </form>
      </section>

      <section className="panel" aria-label="Risk policy">
        <h2 className="section-title">Risk policy</h2>
        <p className="hint">
          Library {props.policy.library_version}, policy version {props.policy.policy_version}.
          Ratings are likelihood × consequence on 1 to 5 scales: Moderate from {bands.moderate},
          High from {bands.high}, Critical from {bands.critical}. These are your organisation&apos;s
          planning categories, not measured probabilities. Stop conditions (no satellite device on
          a remote route, a confirmed closure, missing emergency arrangements) always apply.
        </p>
        {tier !== "ENTERPRISE" ? (
          <p className="notice">
            Your plan is {tier.toLowerCase()}. Changing ratings is part of the Enterprise plan; you
            can see the ratings in use below.
          </p>
        ) : null}
        <form method="post" className="form" onSubmit={savePolicy} aria-label="Hazard ratings">
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Hazard</th>
                  <th>Likelihood</th>
                  <th>Consequence</th>
                  <th>Likelihood with controls</th>
                </tr>
              </thead>
              <tbody>
                {hazards.map((h) => (
                  <tr key={h.key}>
                    <td>{h.title}</td>
                    {(["likelihood", "consequence", "residual_likelihood"] as const).map((f) => (
                      <td key={f}>
                        <input
                          aria-label={`${h.title} ${f.replace("_", " ")}`}
                          name={`${h.key}.${f}`}
                          type="number"
                          min={1}
                          max={5}
                          defaultValue={h[f]}
                          disabled={tier !== "ENTERPRISE"}
                        />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {tier === "ENTERPRISE" ? (
            <button type="submit" className="button" disabled={busy}>
              Save ratings
            </button>
          ) : null}
        </form>
      </section>
    </div>
  );
}
