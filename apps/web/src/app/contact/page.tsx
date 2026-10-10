import type { Metadata } from "next";
import Link from "next/link";

import { PrivacyRequestForm } from "@/components/legal/PrivacyRequestForm";
import { PublicShell } from "@/components/public/PublicShell";
import { OPERATOR } from "@/lib/legal";

export const metadata: Metadata = {
  title: "Contact us",
  description: "How to reach ApprovalReady, and how to make a privacy request.",
  alternates: { canonical: "/contact" },
};

export default function ContactPage() {
  const email = OPERATOR.email;
  return (
    <PublicShell>
      <article className="guide legal" aria-labelledby="contact-title">
        <h1 id="contact-title" className="page-title">
          Contact us
        </h1>
        <p className="lede">
          Email us at <a href={`mailto:${email}`}>{email}</a>.
        </p>

        <section aria-labelledby="privacy-request-title">
          <h2 id="privacy-request-title" className="section-title">
            Privacy requests
          </h2>
          <p>
            Ask to see, correct or delete the personal information we hold about you, or make a
            privacy complaint. We reply within 30 days. If you have an account, you can also
            download your data or close your account yourself from your{" "}
            <Link href="/account#your-data">account page</Link>. Our{" "}
            <Link href="/privacy">Privacy Policy</Link> explains what we hold and why.
          </p>
          <PrivacyRequestForm />
        </section>
      </article>
    </PublicShell>
  );
}
