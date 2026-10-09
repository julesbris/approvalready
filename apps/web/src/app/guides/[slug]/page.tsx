import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { GuideArticle } from "@/components/public/GuideArticle";
import { PublicShell } from "@/components/public/PublicShell";
import { GUIDES, guide } from "@/lib/guides";

type Props = { params: Promise<{ slug: string }> };

export const dynamicParams = false;

export function generateStaticParams() {
  return GUIDES.map((g) => ({ slug: g.slug }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const found = guide((await params).slug);
  if (!found) return {};
  return {
    title: found.title,
    description: found.description,
    alternates: { canonical: `/guides/${found.slug}` },
    // Search engines only index a guide once a person has verified its sources (RISKS.md R11).
    robots: found.verification === "VERIFIED" ? undefined : { index: false, follow: true },
  };
}

export default async function GuidePage({ params }: Props) {
  const found = guide((await params).slug);
  if (!found) notFound();
  return (
    <PublicShell>
      <GuideArticle guide={found} />
    </PublicShell>
  );
}
