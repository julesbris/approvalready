"use client";

import type { AccountActionOut } from "@approvalready/shared-types";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { useAction } from "@/components/admin/useAction";
import { FormError, FormNotice } from "@/components/auth/FormStatus";
import { ACCOUNT_ACTIONS } from "@/lib/accounts";
import { apiRequest } from "@/lib/client-api";

/** Staff: the support actions this account allows. Each asks first; the ones that need a
 * reason (kept in the audit log) only run once one is given. */
export function AccountActions({ accountId, actions }: { accountId: string; actions: string[] }) {
  const router = useRouter();
  const { busy, error, fields, run, setError } = useAction();
  const [reason, setReason] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const needsReason = actions.some((a) => ACCOUNT_ACTIONS[a]?.needsReason);

  async function perform(action: string) {
    const info = ACCOUNT_ACTIONS[action];
    if (info?.needsReason && !reason.trim()) {
      setError("Say why first (it is kept in the audit log).");
      return;
    }
    if (!window.confirm(info?.confirm ?? "Are you sure?")) return;
    setDone(null);
    const result = await run(() =>
      apiRequest<AccountActionOut>("POST", `/admin/accounts/${accountId}/actions`, {
        action,
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
    <form method="post" className="form" onSubmit={(e) => e.preventDefault()}>
      {done ? <FormNotice>{done}</FormNotice> : null}
      {actions.length === 0 ? (
        <p className="muted">Nothing to do for this account here.</p>
      ) : (
        <>
          {needsReason ? (
            <label>
              Reason (needed to reset two-step sign-in or suspend)
              <textarea
                name="reason"
                rows={2}
                maxLength={500}
                value={reason}
                aria-invalid={fields.reason ? true : undefined}
                onChange={(e) => setReason(e.target.value)}
              />
            </label>
          ) : null}
          <FormError message={error} />
          <ul className="plain-list">
            {actions.map((action) => {
              const info = ACCOUNT_ACTIONS[action];
              return (
                <li key={action}>
                  <button
                    type="button"
                    className={
                      action === "suspend" || action === "reset_two_step"
                        ? "button button-secondary"
                        : "button"
                    }
                    disabled={busy}
                    onClick={() => perform(action)}
                  >
                    {info?.label ?? action}
                  </button>
                  {info ? <p className="hint">{info.help}</p> : null}
                </li>
              );
            })}
          </ul>
        </>
      )}
    </form>
  );
}
