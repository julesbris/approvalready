"use client";

import { useRouter } from "next/navigation";

import { useAction } from "@/components/admin/useAction";
import { FormError } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";

/** Send an application that wasn't approved back for checking. */
export function ResubmitButton({ organisationId }: { organisationId: string }) {
  const router = useRouter();
  const { busy, error, run } = useAction();
  async function resubmit() {
    const done = await run(() =>
      apiRequest("POST", `/organisations/${organisationId}/partner/resubmit`),
    );
    if (done !== null) router.refresh();
  }
  return (
    <>
      <FormError message={error} />
      <div className="button-row">
        <button type="button" className="button" disabled={busy} onClick={() => void resubmit()}>
          Send my application again
        </button>
      </div>
    </>
  );
}
