/**
 * Public site address and what search engines may index (Milestone 19: sitemap and robots).
 * SITE_URL is set by docker-compose.prod.yml (https://PRIMARY_DOMAIN); without it the
 * request's host is used.
 */
import { GUIDES } from "@/lib/guides";

export function siteUrl(configured: string | undefined, host: string | null): string {
  if (configured) return configured.replace(/\/+$/, "");
  return host ? `https://${host}` : "http://localhost:3000";
}

/** Public pages for the sitemap. Unverified guides are kept out of search (RISKS.md R11). */
export function sitemapPaths(): string[] {
  return [
    "/",
    "/guides",
    ...GUIDES.filter((g) => g.verification === "VERIFIED").map((g) => `/guides/${g.slug}`),
    "/contact",
    "/privacy",
    "/terms",
  ];
}

/** Signed-in areas and the API proxy: nothing there for search engines. */
export const PRIVATE_PATHS = [
  "/account",
  "/admin",
  "/api/",
  "/invitations",
  "/notifications",
  "/partner",
  "/projects",
  "/review",
] as const;
