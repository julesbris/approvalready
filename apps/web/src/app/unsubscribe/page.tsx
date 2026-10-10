import type { Metadata } from "next";
import Link from "next/link";

import { AuthShell } from "@/components/AuthShell";
import { Unsubscribe } from "@/components/account/Unsubscribe";
import { firstParam } from "@/lib/redirect";

export const metadata: Metadata = { title: "Unsubscribe", robots: { index: false } };

type Props = { searchParams: Promise<Record<string, string | string[] | undefined>> };

export default async function UnsubscribePage({ searchParams }: Props) {
  const token = firstParam((await searchParams).token);
  return (
    <AuthShell title="Email settings">
      {token ? (
        <Unsubscribe token={token} />
      ) : (
        <p>
          This link is incomplete. <Link href="/account#notifications">Sign in</Link> to choose
          which emails you get.
        </p>
      )}
    </AuthShell>
  );
}
