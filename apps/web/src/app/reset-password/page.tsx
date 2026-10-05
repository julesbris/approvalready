import type { Metadata } from "next";
import Link from "next/link";

import { AuthShell } from "@/components/AuthShell";
import { ResetPasswordForm } from "@/components/auth/ResetPasswordForm";
import { firstParam } from "@/lib/redirect";

export const metadata: Metadata = { title: "Choose a new password", robots: { index: false } };

type Props = { searchParams: Promise<Record<string, string | string[] | undefined>> };

export default async function ResetPasswordPage({ searchParams }: Props) {
  const token = firstParam((await searchParams).token);
  return (
    <AuthShell title="Choose a new password">
      {token ? (
        <ResetPasswordForm token={token} />
      ) : (
        <p>
          This link is incomplete. <Link href="/forgot-password">Request a new one</Link>.
        </p>
      )}
    </AuthShell>
  );
}
