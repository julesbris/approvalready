import type { MetadataRoute } from "next";
import { headers } from "next/headers";

import { siteUrl, sitemapEntries } from "@/lib/site";

export const dynamic = "force-dynamic";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const base = siteUrl(process.env.SITE_URL, (await headers()).get("host"));
  return sitemapEntries().map(({ path, lastModified }) => ({
    url: `${base}${path === "/" ? "" : path}`,
    ...(lastModified ? { lastModified } : {}),
  }));
}
