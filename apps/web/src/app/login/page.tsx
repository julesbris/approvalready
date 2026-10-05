import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { AuthShell } from "@/components/AuthShell";
import { LoginForm } from "@/components/auth/LoginForm";
import { safeNext } from "@/lib/redirect";
import { getSession } from "@/lib/session";

export const metadata: Metadata = { title: "Sign in", robots: { index: false } };

type Props = { searchParams: Promise<Record<string, string | string[] | undefined>> };

export default async function LoginPage({ searchParams }: Props) {
  const next = safeNext((await searchParams).next);
  if (await getSession()) redirect(next);
  return (
    <AuthShell
      title="Sign in"
      footer={
        <>
          New to ApprovalReady? <Link href="/register">Create an account</Link>
        </>
      }
    >
      <LoginForm next={next} />
    </AuthShell>
  );
}
