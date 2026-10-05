import type { Metadata } from "next";
import Link from "next/link";
import { connection } from "next/server";

import { AuthShell } from "@/components/AuthShell";
import { RegisterForm } from "@/components/auth/RegisterForm";

export const metadata: Metadata = { title: "Create an account", robots: { index: false } };

export default async function RegisterPage() {
  await connection(); // per-request render so the CSP nonce applies
  return (
    <AuthShell
      title="Create your account"
      intro="One account covers every ApprovalReady product. We'll email you a link to confirm your address."
      footer={
        <>
          Already have an account? <Link href="/login">Sign in</Link>
        </>
      }
    >
      <RegisterForm />
    </AuthShell>
  );
}
