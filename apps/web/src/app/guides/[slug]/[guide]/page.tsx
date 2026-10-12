import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { PublicGuideArticle } from "@/components/public/PublicGuideArticle";
import { PublicShell } from "@/components/public/PublicShell";
import {
  CARD_SIZES,
  cardAlt,
  cardPath,
  guideJsonLd,
  jsonLdScript,
  metaDescription,
  pageTitle,
  PUBLIC_GUIDES,
  publicGuide,
} from "@/lib/publicGuides";
import { INDEX_UNVERIFIED_GUIDES, PUBLIC_SITE_URL } from "@/lib/site";

type Props = { params: Promise<{ slug: string; guide: string }> };

export const dynamicParams = false;

/** Every approval guide at `/guides/<state>/<slug>`. */
export function generateStaticParams() {
  return PUBLIC_GUIDES.map((g) => ({ slug: g.state.segment, guide: g.slug }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug, guide } = await params;
  const found = publicGuide(slug, guide);
  if (!found) return {};
  const title = pageTitle(found);
  const description = metaDescription(found);
  const image = {
    url: cardPath(found, "wide"),
    ...CARD_SIZES.wide,
    alt: cardAlt(found),
    type: "image/jpeg",
  };
  return {
    title,
    description,
    alternates: { canonical: found.path },
    openGraph: {
      title,
      description,
      type: "article",
      url: found.path,
      siteName: "ApprovalReady",
      locale: "en_AU",
      modifiedTime: found.checked_on,
      images: [image],
    },
    twitter: { card: "summary_large_image", title, description, images: [image] },
    robots: INDEX_UNVERIFIED_GUIDES ? undefined : { index: false, follow: true },
  };
}

export default async function ApprovalGuidePage({ params }: Props) {
  const { slug, guide } = await params;
  const found = publicGuide(slug, guide);
  if (!found) notFound();
  return (
    <PublicShell>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: jsonLdScript(guideJsonLd(found, PUBLIC_SITE_URL)) }}
      />
      <PublicGuideArticle guide={found} />
    </PublicShell>
  );
}
