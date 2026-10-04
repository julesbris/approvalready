import type { Metadata } from "next";
import Link from "next/link";
import { connection } from "next/server";

import { AuthShell } from "@/components/AuthShell";
import { ForgotPasswordForm } from "@/components/auth/ForgotPasswordForm";

export const metadata: Metadata = { title: "Reset your password", robots: { index: false } };

export default async function ForgotPasswordPage() {
  await connection();
  return (
    <AuthShell
      title="Reset your password"
      intro="Enter your email address and we'll send you a link to choose a new password."
      footer={<Link href="/login">Back to sign in</Link>}
    >
      <ForgotPasswordForm />
    </AuthShell>
  );
}
