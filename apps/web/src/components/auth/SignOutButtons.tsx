"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { apiRequest } from "@/lib/client-api";

export function SignOutButtons() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  async function signOut(path: "/auth/logout" | "/auth/logout-all") {
    setBusy(true);
    await apiRequest("POST", path);
    router.replace("/login");
    router.refresh();
  }

  return (
    <div className="button-row">
      <button type="button" className="button" disabled={busy} onClick={() => signOut("/auth/logout")}>
        Sign out
      </button>
      <button
        type="button"
        className="button button-secondary"
        disabled={busy}
        onClick={() => signOut("/auth/logout-all")}
      >
        Sign out on all devices
      </button>
    </div>
  );
}
