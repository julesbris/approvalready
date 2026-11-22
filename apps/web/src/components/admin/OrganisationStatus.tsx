"use client";

import type { AccountActionOut } from "@approvalready/shared-types";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useAction } from "@/components/admin/useAction";
import { FormError } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";

/** Platform administrators: suspend or restore a business workspace from its member's page. */
export function OrganisationStatus({
  accountId,
  organisationId,
  name,
  status,
}: {
  accountId: string;
  organisationId: string;
  name: string;
  status: string;
}) {
  const router = useRouter();
  const { busy, error, run, setError } = useAction();
  const [reason, setReason] = useState("");
  const suspended = status === "SUSPENDED";

  async function change() {
    if (!suspended && !reason.trim()) {
      setError("Say why first (it is kept in the audit log).");
      return;
    }
    const question = suspended
      ? `Open ${name} again for all its members?`
      : `Suspend ${name}? Every member loses access until it is restored, and they are emailed.`;
    if (!window.confirm(question)) return;
    const result = await run(() =>
      apiRequest<AccountActionOut>(
        "PUT",
        `/admin/accounts/${accountId}/organisations/${organisationId}/status`,
        { status: suspended ? "ACTIVE" : "SUSPENDED", reason },
      ),
    );
    if (result) {
      setReason("");
      router.refresh();
    }
  }

  return (
    <div className="form">
      {suspended ? null : (
        <label>
          Reason to suspend
          <input
            name="reason"
            maxLength={500}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </label>
      )}
      <FormError message={error} />
      <button
        type="button"
        className={suspended ? "button" : "button button-secondary"}
        disabled={busy}
        onClick={() => void change()}
      >
        {suspended ? "Restore workspace" : "Suspend workspace"}
      </button>
    </div>
  );
}
