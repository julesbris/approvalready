import type { MetadataRoute } from "next";
import { headers } from "next/headers";

import { PRIVATE_PATHS, siteUrl } from "@/lib/site";

export const dynamic = "force-dynamic";

export default async function robots(): Promise<MetadataRoute.Robots> {
  const base = siteUrl(process.env.SITE_URL, (await headers()).get("host"));
  return {
    rules: { userAgent: "*", allow: "/", disallow: [...PRIVATE_PATHS] },
    sitemap: `${base}/sitemap.xml`,
  };
}
