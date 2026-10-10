import type { Metadata } from "next";
import Link from "next/link";

import { PublicShell } from "@/components/public/PublicShell";
import { OPERATOR, POLICY_VERSIONS, policyDate } from "@/lib/legal";

export const metadata: Metadata = {
  title: "Privacy Policy",
  description:
    "What personal information ApprovalReady collects, why, who sees it and your choices.",
  alternates: { canonical: "/privacy" },
};

// Describes what the platform actually does (Milestone 19). Change the text, then change
// POLICY_VERSIONS.privacy and apps/api/app/modules/privacy/policies.json together.
export default function PrivacyPage() {
  const email = OPERATOR.email;
  return (
    <PublicShell>
      <article className="guide legal" aria-labelledby="privacy-title">
        <h1 id="privacy-title" className="page-title">
          Privacy Policy
        </h1>
        <p className="lede">Dated {policyDate(POLICY_VERSIONS.privacy)}.</p>
        <p>
          This policy explains how {OPERATOR.name} (&quot;we&quot;, &quot;us&quot;) handles
          personal information when you use our website and apps. We follow the Australian
          Privacy Principles in the <em>Privacy Act 1988</em> (Cth). If anything here is
          unclear, <Link href="/contact">contact us</Link>.
        </p>

        <section>
          <h2 className="section-title">What we collect</h2>
          <ul>
            <li>
              <strong>Your account:</strong> your name, email address, password (stored only as
              a one-way hash, never readable by us) and, if you turn on two-step sign-in, the
              key for your authenticator app.
            </li>
            <li>
              <strong>Your organisations:</strong> business, practice or partner names, ABNs,
              the people you invite and their roles.
            </li>
            <li>
              <strong>Your projects:</strong> the answers you give in questionnaires, property
              addresses and lot details, vessel details, business profiles, tasks, reminders,
              rental and sale records (which may include details of tenants, buyers or
              applicants that you enter), and the files you upload.
            </li>
            <li>
              <strong>Reviews and referrals:</strong> messages and decisions in professional
              reviews, and the details you agree to share when you ask to be referred to a
              partner business.
            </li>
            <li>
              <strong>Payments:</strong> what you bought, amounts, invoices and payment
              references. Card details go straight to our payment processor, Stripe; we never
              see or store them.
            </li>
            <li>
              <strong>Technical information:</strong> your IP address, browser and device type,
              and the times you sign in and make changes. We keep a security log of important
              actions on accounts.
            </li>
          </ul>
          <p>
            Please don&apos;t upload sensitive information (such as health information) or
            identity documents unless a task needs it. If you give us information about
            someone else, such as a tenant or a business partner, make sure they know you are
            sharing it with us.
          </p>
        </section>

        <section>
          <h2 className="section-title">How we collect it</h2>
          <p>
            Almost everything comes from you, as you use the service. Some comes from public
            sources at your request: when you search for an address or vessel, we look it up in
            Queensland Government mapping services and the Australian Maritime Safety
            Authority&apos;s vessel list. Professionals and partners add information when they
            work on a review or referral you asked for.
          </p>
        </section>

        <section>
          <h2 className="section-title">Why we use it</h2>
          <ul>
            <li>
              To run your account and the service: assessments, reports, reminders, emails and
              notifications.
            </li>
            <li>To arrange professional reviews and referrals you ask for.</li>
            <li>To take payments and keep the records tax law requires.</li>
            <li>To keep accounts and the service secure and to prevent misuse.</li>
            <li>To answer your questions and requests.</li>
            <li>
              To improve the service, using totals and trends rather than individual records
              where we can.
            </li>
          </ul>
          <p>
            We don&apos;t sell personal information, and we don&apos;t use it for advertising.
            We only send emails about your account and projects; there is no marketing list.
          </p>
        </section>

        <section>
          <h2 className="section-title">Who sees it</h2>
          <p>
            People in an organisation see that organisation&apos;s projects, according to their
            role. Our staff can see what they need to support the service. Beyond that, we
            share personal information only as follows:
          </p>
          <ul>
            <li>
              <strong>Professionals</strong> see a project&apos;s details and the files you
              share when you request a review.
            </li>
            <li>
              <strong>Partner businesses</strong> see the details you agree to release when you
              ask for a referral. You choose what is released and can withdraw your consent.
            </li>
            <li>
              <strong>Service providers</strong> who process information for us, listed below.
            </li>
            <li>
              <strong>Authorities</strong>, when the law requires it.
            </li>
          </ul>
          <table>
            <thead>
              <tr>
                <th scope="col">Provider</th>
                <th scope="col">What for</th>
                <th scope="col">Where the information is held</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Kamatera</td>
                <td>Hosts our servers, database, uploaded files and backups</td>
                <td>Sydney, Australia</td>
              </tr>
              <tr>
                <td>Stripe</td>
                <td>Payments and invoices</td>
                <td>Australia, the United States and other countries Stripe operates in</td>
              </tr>
              <tr>
                <td>Google Workspace</td>
                <td>Sending our emails, and our own mailbox</td>
                <td>Australia, the United States and other countries Google operates in</td>
              </tr>
              <tr>
                <td>Anthropic</td>
                <td>
                  If we switch on AI drafting: writing plain-language explanations and draft
                  notes from a project&apos;s findings and answers. Under its commercial terms
                  Anthropic does not train its models on this information.
                </td>
                <td>The United States</td>
              </tr>
              <tr>
                <td>Sentry</td>
                <td>If we switch on error tracking: technical reports when something breaks</td>
                <td>The United States</td>
              </tr>
            </tbody>
          </table>
          <p>
            When you choose a password, we check it against Have I Been Pwned&apos;s list of
            breached passwords. Only the first five characters of a one-way hash of the
            password are sent, never the password or your email address.
          </p>
        </section>

        <section>
          <h2 className="section-title">Cookies</h2>
          <p>
            We only use cookies the service needs: one that keeps you signed in, one that
            protects your forms from cross-site attacks, and a short-lived one during two-step
            sign-in. We don&apos;t use analytics, advertising or tracking cookies.
          </p>
        </section>

        <section>
          <h2 className="section-title">Keeping it safe</h2>
          <p>
            Connections are encrypted, passwords are hashed, staff accounts need two-step
            sign-in, each organisation&apos;s records are kept separate in the database,
            uploaded files are checked for viruses, and we keep backups and a tamper-evident
            security log. If a data breach is likely to cause you serious harm, we will tell
            you and the Office of the Australian Information Commissioner, as the Notifiable
            Data Breaches scheme requires.
          </p>
        </section>

        <section>
          <h2 className="section-title">How long we keep it</h2>
          <p>
            We keep your information while your account is open. When you close your account,
            your name, email address and sign-in details are removed straight away, and within
            30 days we delete the projects, answers and files in your personal workspace. We
            keep what the law requires us to keep, such as payment records (generally five
            years for tax law), and the security log. Records of a business organisation stay
            with that organisation. Backup copies expire on a rolling schedule.
          </p>
        </section>

        <section>
          <h2 className="section-title">Your choices</h2>
          <ul>
            <li>
              <strong>See your information:</strong> download a copy of your account and
              personal workspace from your account page at any time.
            </li>
            <li>
              <strong>Correct it:</strong> edit your projects and profiles yourself, or ask us.
            </li>
            <li>
              <strong>Close your account:</strong> from your account page.
            </li>
            <li>
              <strong>Ask us anything else</strong>, or make a request on someone&apos;s
              behalf, on our <Link href="/contact">contact page</Link> or at{" "}
              <a href={`mailto:${email}`}>{email}</a>.
            </li>
          </ul>
          <p>
            We answer requests within 30 days and don&apos;t charge for them. If we can&apos;t
            do what you ask, we will tell you why. You can deal with us without giving your
            name for general questions, but we need to know who you are to act on an account.
          </p>
        </section>

        <section>
          <h2 className="section-title">Complaints</h2>
          <p>
            If you think we have mishandled your personal information, tell us on the{" "}
            <Link href="/contact">contact page</Link>. We will look into it and reply within 30
            days. If you&apos;re not satisfied with our answer, you can complain to the Office of
            the Australian Information Commissioner at{" "}
            <a href="https://www.oaic.gov.au" rel="noopener">
              oaic.gov.au
            </a>{" "}
            or on 1300 363 992.
          </p>
        </section>

        <section>
          <h2 className="section-title">Changes to this policy</h2>
          <p>
            When we change this policy we will update its date, and ask you to read and agree
            to the new version the next time you sign in.
          </p>
        </section>
      </article>
    </PublicShell>
  );
}
