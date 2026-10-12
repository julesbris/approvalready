"use client";

import type { RedirectOut } from "@approvalready/shared-types";

import { useAction } from "@/components/admin/useAction";
import { FormError } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";

/** The one button: off to Stripe's page to add a card and start the membership. */
export function StartMembership({
  organisationId,
  trial,
}: {
  organisationId: string;
  trial: boolean;
}) {
  const { busy, error, run } = useAction();

  async function start() {
    const data = await run(() =>
      apiRequest<RedirectOut>(
        "POST",
        `/organisations/${organisationId}/billing/membership/checkout`,
      ),
    );
    if (data) window.location.assign(data.url);
  }

  return (
    <>
      <FormError message={error} />
      <div className="button-row">
        <button type="button" className="button button-large" disabled={busy} onClick={start}>
          {busy
            ? "Opening Stripe…"
            : trial
              ? "Add card and start my free month"
              : "Add card and join"}
        </button>
      </div>
    </>
  );
}
