import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { GuideArticle } from "@/components/public/GuideArticle";
import { PublicShell } from "@/components/public/PublicShell";
import { StateGuides } from "@/components/public/StateGuides";
import { GUIDES, guide } from "@/lib/guides";
import {
  GUIDE_STATES,
  guideState,
  jsonLdScript,
  NATIONAL,
  placeName,
  PUBLIC_GUIDES,
  stateJsonLd,
} from "@/lib/publicGuides";
import { INDEX_UNVERIFIED_GUIDES, PUBLIC_SITE_URL } from "@/lib/site";

type Props = { params: Promise<{ slug: string }> };

export const dynamicParams = false;

/** A sourced guide (`/guides/<slug>`) or a state's guides (`/guides/<state>`). */
export function generateStaticParams() {
  return [
    ...GUIDES.map((g) => ({ slug: g.slug })),
    ...GUIDE_STATES.map((s) => ({ slug: s.segment })),
  ];
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const slug = (await params).slug;
  const state = guideState(slug);
  if (state) {
    const place = placeName(state);
    const title =
      state.segment === NATIONAL
        ? "Australia-wide approval guides: ABN, GST, importing and more"
        : `${place} approval guides: building, business, selling, renting and boats`;
    const count = PUBLIC_GUIDES.filter((g) => g.state.segment === state.segment).length;
    return {
      title,
      description: `${count} free step-by-step guides to approvals, licences and registrations in ${place}, with official forms, fees, timeframes and contacts.`,
      alternates: { canonical: `/guides/${state.segment}` },
      openGraph: { title, type: "website", url: `/guides/${state.segment}` },
    };
  }
  const found = guide(slug);
  if (!found) return {};
  return {
    title: found.title,
    description: found.description,
    alternates: { canonical: `/guides/${found.slug}` },
    // Search engines index a guide once a person has verified its sources, or before that
    // when unverified guides are allowed into search (RISKS.md R11).
    robots:
      found.verification === "VERIFIED" || INDEX_UNVERIFIED_GUIDES
        ? undefined
        : { index: false, follow: true },
  };
}

export default async function GuidePage({ params }: Props) {
  const slug = (await params).slug;
  const state = guideState(slug);
  if (state) {
    const guides = PUBLIC_GUIDES.filter((g) => g.state.segment === state.segment);
    return (
      <PublicShell>
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{
            __html: jsonLdScript(stateJsonLd(state, guides, PUBLIC_SITE_URL)),
          }}
        />
        <StateGuides state={state} />
      </PublicShell>
    );
  }
  const found = guide(slug);
  if (!found) notFound();
  return (
    <PublicShell>
      <GuideArticle guide={found} />
    </PublicShell>
  );
}
