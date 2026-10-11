import type { Metadata } from "next";

import { NewsletterLink } from "@/components/marketing/NewsletterLink";
import { NewsletterSignUp } from "@/components/marketing/NewsletterSignUp";
import { PublicShell } from "@/components/public/PublicShell";
import { firstParam } from "@/lib/redirect";

export const metadata: Metadata = {
  title: "Guides by email",
  description:
    "Get ApprovalReady's step-by-step approval guides by email: what to have ready, every step, the costs, timeframes and who to contact.",
  alternates: { canonical: "/newsletter" },
};

type Props = { searchParams: Promise<Record<string, string | string[] | undefined>> };

export default async function NewsletterPage({ searchParams }: Props) {
  const params = await searchParams;
  const confirm = firstParam(params.confirm);
  const unsubscribe = firstParam(params.unsubscribe);
  return (
    <PublicShell>
      <article className="guide legal" aria-labelledby="newsletter-title">
        <h1 id="newsletter-title" className="page-title">
          Guides by email
        </h1>
        {confirm ? <NewsletterLink action="confirm" token={confirm} /> : null}
        {unsubscribe ? <NewsletterLink action="unsubscribe" token={unsubscribe} /> : null}
        {confirm ? null : (
          <>
            <p className="lede">
              One approval explained properly in each email: what to have ready, every step in
              order, the forms, what it costs, how long it takes and who to call. Gathered from
              official sources, with the links to check them.
            </p>
            <NewsletterSignUp />
          </>
        )}
      </article>
    </PublicShell>
  );
}
