"use client";

import type { MembershipOut } from "@approvalready/shared-types";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { apiRequest } from "@/lib/client-api";

export function OrgSwitcher({
  organisations,
  activeId,
}: {
  organisations: MembershipOut[];
  activeId: string | null;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (organisations.length < 2) {
    const only = organisations[0];
    return only ? <span className="org-current">{only.name}</span> : null;
  }

  async function change(organisationId: string) {
    setBusy(true);
    setError(null);
    const result = await apiRequest("PUT", "/auth/session/organisation", {
      organisation_id: organisationId,
    });
    setBusy(false);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    // Project ids belong to one organisation, so start again from the project list.
    router.push("/projects");
    router.refresh();
  }

  return (
    <label className="org-switcher">
      <span className="visually-hidden">Active organisation</span>
      <select
        value={activeId ?? ""}
        disabled={busy}
        onChange={(event) => change(event.target.value)}
        aria-describedby={error ? "org-switch-error" : undefined}
      >
        {organisations.map((org) => (
          <option key={org.organisation_id} value={org.organisation_id}>
            {org.name}
          </option>
        ))}
      </select>
      {error ? (
        <span id="org-switch-error" role="alert" className="field-error">
          {error}
        </span>
      ) : null}
    </label>
  );
}
