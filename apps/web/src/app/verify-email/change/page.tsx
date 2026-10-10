import type { Metadata } from "next";
import Link from "next/link";

import { AuthShell } from "@/components/AuthShell";
import { TokenAction } from "@/components/auth/TokenAction";
import { firstParam } from "@/lib/redirect";

export const metadata: Metadata = { title: "Confirm your new email", robots: { index: false } };

type Props = { searchParams: Promise<Record<string, string | string[] | undefined>> };

/** The link from a change of email address (Milestone 28). */
export default async function ConfirmEmailChangePage({ searchParams }: Props) {
  const token = firstParam((await searchParams).token);
  return (
    <AuthShell title="Confirm your new email address">
      {token ? (
        <TokenAction
          path="/auth/email-change/confirm"
          token={token}
          label="Use this email address"
          success="Done. Your account now uses this email address to sign in."
          next={{ href: "/account", label: "Go to your account" }}
        />
      ) : (
        <p>
          This link is incomplete. <Link href="/account#security">Open your account</Link> to
          ask for a new one.
        </p>
      )}
    </AuthShell>
  );
}
