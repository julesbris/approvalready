import type { Metadata } from "next";
import Link from "next/link";

import { PublicShell } from "@/components/public/PublicShell";
import { OPERATOR, POLICY_VERSIONS, policyDate } from "@/lib/legal";

export const metadata: Metadata = {
  title: "Terms of Use",
  description: "The terms for using ApprovalReady.",
  alternates: { canonical: "/terms" },
};

// Change the text, then change POLICY_VERSIONS.terms and
// apps/api/app/modules/privacy/policies.json together (Milestone 19).
export default function TermsPage() {
  const name = OPERATOR.name;
  return (
    <PublicShell>
      <article className="guide legal" aria-labelledby="terms-title">
        <h1 id="terms-title" className="page-title">
          Terms of Use
        </h1>
        <p className="lede">Dated {policyDate(POLICY_VERSIONS.terms)}.</p>
        <p>
          These terms apply when you use {name} (&quot;we&quot;, &quot;us&quot;). By creating
          an account or using the service you agree to them. Our{" "}
          <Link href="/privacy">Privacy Policy</Link> explains how we handle personal
          information.
        </p>

        <section>
          <h2 className="section-title">1. What {name} is, and isn&apos;t</h2>
          <p>
            {name} helps you work out which approvals, licences and grants may apply to you,
            prepare evidence and documents, and find professional help. Our results come from
            published regulatory sources, and each one shows how confident we are and which
            sources it relies on.
          </p>
          <p>
            {name} provides general information and preparation tools. It is not legal,
            planning, building, financial or other professional advice, and it doesn&apos;t
            grant any approval. Councils, government agencies and other authorities make those
            decisions, and their rules change. Before you rely on a result, for example to buy
            land, start building, sign a contract or lodge an application, check it with the
            authority or a qualified professional.
          </p>
        </section>

        <section>
          <h2 className="section-title">2. Your account</h2>
          <ul>
            <li>You must be 18 or older and give us accurate information.</li>
            <li>
              Keep your password and two-step sign-in codes to yourself. You are responsible for
              what happens in your account; tell us straight away if you think someone else has
              used it.
            </li>
            <li>
              If you create an organisation, you confirm you may act for it. Its administrators
              decide who can see and change its projects.
            </li>
          </ul>
        </section>

        <section>
          <h2 className="section-title">3. Your content</h2>
          <p>
            You own the answers, files and other content you put into {name}. You allow us to
            store, process, copy and show it as needed to provide the service to you and the
            people you share it with, including professionals and partners you choose. You
            confirm you have the right to give us that content, including any personal
            information about other people in it.
          </p>
        </section>

        <section>
          <h2 className="section-title">4. Fair use</h2>
          <p>Don&apos;t use {name} to:</p>
          <ul>
            <li>
              break the law or anyone&apos;s rights, or upload anything harmful or misleading;
            </li>
            <li>
              try to get into accounts or data that aren&apos;t yours, test or attack our
              security, or overload the service;
            </li>
            <li>copy our content or rules in bulk, or scrape the service;</li>
            <li>misuse referrals, for example by giving partners false details.</li>
          </ul>
        </section>

        <section>
          <h2 className="section-title">5. Professionals and partners</h2>
          <p>
            Professionals who review projects and partner businesses who receive referrals are
            independent businesses, not our employees. We check the credentials we say we
            check, but we don&apos;t supervise their work. What you agree with them, including
            their fees, is between you and them. We only share your details with a partner
            when you consent to it.
          </p>
        </section>

        <section>
          <h2 className="section-title">6. Prices and payments</h2>
          <ul>
            <li>
              Prices are in Australian dollars and shown before you pay; your invoice shows any
              GST. Payments are processed by Stripe.
            </li>
            <li>
              Subscriptions renew each period until you cancel. You can cancel at any time
              under Billing; the plan then ends at the end of the period you have paid for.
            </li>
            <li>
              Refunds are available where the Australian Consumer Law requires them, and
              otherwise at our discretion.
            </li>
          </ul>
        </section>

        <section>
          <h2 className="section-title">7. Your rights under consumer law</h2>
          <p>
            Our services come with guarantees that can&apos;t be excluded under the Australian
            Consumer Law, and nothing in these terms limits them. Apart from those guarantees,
            and as far as the law allows, we provide the service &quot;as is&quot;; we
            aren&apos;t liable for indirect or consequential loss; and our total liability to
            you is limited to supplying the service again or the fees you paid us in the 12
            months before the claim.
          </p>
        </section>

        <section>
          <h2 className="section-title">8. Our content</h2>
          <p>
            The service, our guides, rules and report formats belong to us or our licensors.
            You may use the reports and documents we generate for you for your own purposes,
            including sharing them with authorities and advisers.
          </p>
        </section>

        <section>
          <h2 className="section-title">9. Changes, suspension and closing</h2>
          <p>
            We may change or stop parts of the service; if that affects something you have
            paid for, we will tell you and offer a fair outcome. We may suspend an account that
            breaks these terms or puts others at risk. You can close your account at any time
            from your account page.
          </p>
        </section>

        <section>
          <h2 className="section-title">10. Changes to these terms</h2>
          <p>
            When we change these terms we will update their date and ask you to agree to the
            new version the next time you sign in.
          </p>
        </section>

        <section>
          <h2 className="section-title">11. General</h2>
          <p>
            These terms are governed by the laws of {OPERATOR.state}, Australia. If part of
            them can&apos;t be enforced, the rest still applies. Questions?{" "}
            <Link href="/contact">Contact us</Link>.
          </p>
        </section>
      </article>
    </PublicShell>
  );
}
