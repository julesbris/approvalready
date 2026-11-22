"use client";

import type { AccountActionOut } from "@approvalready/shared-types";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { useAction } from "@/components/admin/useAction";
import { FormError, FormNotice } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";

export const STAFF_ROLE_CHOICES: { value: string; label: string; help: string }[] = [
  { value: "", label: "No staff role", help: "A normal customer account." },
  {
    value: "STAFF",
    label: "Staff",
    help:
      "Can look up accounts and stuck projects, add notes, email customers, check sources, " +
      "write rules and verify professionals and partners.",
  },
  {
    value: "ADMIN",
    label: "Platform administrator",
    help:
      "Everything staff can do, plus suspend accounts, reset sign-ins, publish rules, " +
      "refunds, billing, privacy requests and marketing.",
  },
  {
    value: "SUPERADMIN",
    label: "Super administrator",
    help:
      "Everything, including giving and taking away staff roles. Keep this to one or two " +
      "people.",
  },
];

/** Super administrators: give, change or take away this person's staff role. */
export function StaffRole({ accountId, current }: { accountId: string; current: string | null }) {
  const router = useRouter();
  const { busy, error, fields, run } = useAction();
  const [role, setRole] = useState(current ?? "");
  const [reason, setReason] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const unchanged = role === (current ?? "");

  async function save(e: FormEvent) {
    e.preventDefault();
    const label = STAFF_ROLE_CHOICES.find((c) => c.value === role)?.label ?? role;
    if (!window.confirm(role ? `Make this person ${label}?` : "Take away their staff access?")) {
      return;
    }
    setDone(null);
    const result = await run(() =>
      apiRequest<AccountActionOut>("PUT", `/admin/accounts/${accountId}/staff-role`, {
        role: role || null,
        reason,
      }),
    );
    if (result) {
      setDone(result.message);
      setReason("");
      router.refresh();
    }
  }

  return (
    <form method="post" className="form" onSubmit={(e) => void save(e)}>
      {done ? <FormNotice>{done}</FormNotice> : null}
      <fieldset>
        <legend>Staff role</legend>
        {STAFF_ROLE_CHOICES.map((c) => (
          <label key={c.value || "none"}>
            <input
              type="radio"
              name="role"
              value={c.value}
              checked={role === c.value}
              onChange={() => setRole(c.value)}
            />{" "}
            {c.label}
            <span className="hint"> {c.help}</span>
          </label>
        ))}
      </fieldset>
      <label>
        Reason (kept in the audit log)
        <input
          name="reason"
          maxLength={500}
          value={reason}
          aria-invalid={fields.reason ? true : undefined}
          onChange={(e) => setReason(e.target.value)}
        />
      </label>
      <FormError message={error} />
      <button type="submit" className="button" disabled={busy || unchanged}>
        Save staff role
      </button>
    </form>
  );
}
