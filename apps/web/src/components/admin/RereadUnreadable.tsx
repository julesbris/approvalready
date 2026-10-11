"use client";

import type { RereadOut } from "@approvalready/shared-types";
import { useState } from "react";

import { useAction } from "@/components/admin/useAction";
import { FormError } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";

/** Read again, in the background, every source the last check couldn't read. */
export function RereadUnreadable({ count }: { count: number }) {
  const action = useAction();
  const [queued, setQueued] = useState<number | null>(null);

  async function reread() {
    const done = await action.run(() =>
      apiRequest<RereadOut>(
        "POST",
        "/admin/source-documents/reread-unreadable",
      ),
    );
    if (done) setQueued(done.queued);
  }

  if (queued !== null) {
    return (
      <p className="muted" role="status">
        {queued === 0
          ? "Nothing to read again."
          : `Reading ${queued} source${queued === 1 ? "" : "s"} again, one at a time. You'll get a notice when it's done; refresh this page to see the results.`}
      </p>
    );
  }
  return (
    <p>
      <button
        type="button"
        className="button"
        onClick={reread}
        disabled={action.busy || count === 0}
      >
        {action.busy ? "Starting…" : "Read unreadable sources again"}
      </button>
      <FormError message={action.error} />
    </p>
  );
}
