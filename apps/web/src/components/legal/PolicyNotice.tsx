"use client";

import type { PolicyOut } from "@approvalready/shared-types";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { useAction } from "@/components/admin/useAction";
import { FormError } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";
import { policyDate } from "@/lib/legal";

/** Asks a signed-in user to agree to Terms of Use / Privacy Policy versions they haven't. */
export function PolicyNotice({ policies }: { policies: PolicyOut[] }) {
  const router = useRouter();
  const { busy, error, run } = useAction();

  async function agree() {
    const left = await run(() =>
      apiRequest<PolicyOut[]>("POST", "/auth/policies/accept", {
        documents: policies.map((p) => p.document),
      }),
    );
    if (left !== null) router.refresh();
  }

  return (
    <section className="notice notice-warning" aria-labelledby="policy-notice-title">
      <h2 id="policy-notice-title" className="subsection-title">
        Please read and agree to our {policies.length > 1 ? "updated policies" : "updated policy"}
      </h2>
      <ul>
        {policies.map((p) => (
          <li key={p.document}>
            <Link href={p.path} target="_blank" rel="noopener">
              {p.title}
            </Link>{" "}
            (dated {policyDate(p.version)})
          </li>
        ))}
      </ul>
      <FormError message={error} />
      <button type="button" className="button" disabled={busy} onClick={agree}>
        I agree
      </button>
    </section>
  );
}
