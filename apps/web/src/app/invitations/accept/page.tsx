import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { AuthShell } from "@/components/AuthShell";
import { TokenAction } from "@/components/auth/TokenAction";
import { firstParam } from "@/lib/redirect";
import { getSession } from "@/lib/session";

export const metadata: Metadata = { title: "Accept invitation", robots: { index: false } };

type Props = { searchParams: Promise<Record<string, string | string[] | undefined>> };

export default async function AcceptInvitationPage({ searchParams }: Props) {
  const token = firstParam((await searchParams).token);
  const session = await getSession();
  if (!session) {
    const back = `/invitations/accept${token ? `?token=${encodeURIComponent(token)}` : ""}`;
    redirect(`/login?next=${encodeURIComponent(back)}`);
  }
  return (
    <AuthShell
      title="Join an organisation"
      intro={
        <>
          You&apos;re signed in as <strong>{session.user.email}</strong>. The invitation must have
          been sent to this address.
        </>
      }
    >
      {token ? (
        <TokenAction
          path="/invitations/accept"
          token={token}
          label="Accept invitation"
          success="You've joined the organisation."
          next={{ href: "/account", label: "Go to your account" }}
        />
      ) : (
        <p>This invitation link is incomplete.</p>
      )}
    </AuthShell>
  );
}
