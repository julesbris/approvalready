import type { Metadata } from "next";
import Link from "next/link";

import { AuthShell } from "@/components/AuthShell";
import { TokenAction } from "@/components/auth/TokenAction";
import { firstParam } from "@/lib/redirect";

export const metadata: Metadata = { title: "Confirm your email", robots: { index: false } };

type Props = { searchParams: Promise<Record<string, string | string[] | undefined>> };

export default async function VerifyEmailPage({ searchParams }: Props) {
  const token = firstParam((await searchParams).token);
  return (
    <AuthShell title="Confirm your email address">
      {token ? (
        <TokenAction
          path="/auth/verify-email"
          token={token}
          label="Confirm my email address"
          success="Your email address is confirmed."
          next={{ href: "/login", label: "Sign in" }}
        />
      ) : (
        <p>
          This link is incomplete. <Link href="/login">Sign in</Link> to request a new one.
        </p>
      )}
    </AuthShell>
  );
}
