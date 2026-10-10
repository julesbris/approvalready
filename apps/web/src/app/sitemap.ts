import type { MetadataRoute } from "next";
import { headers } from "next/headers";

import { siteUrl, sitemapPaths } from "@/lib/site";

export const dynamic = "force-dynamic";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const base = siteUrl(process.env.SITE_URL, (await headers()).get("host"));
  return sitemapPaths().map((path) => ({ url: `${base}${path === "/" ? "" : path}` }));
}
