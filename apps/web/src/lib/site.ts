/**
 * Public site address and what search engines may index (Milestone 19: sitemap and robots).
 * SITE_URL is set by docker-compose.prod.yml (https://PRIMARY_DOMAIN); without it the
 * request's host is used.
 */
import { GUIDES } from "@/lib/guides";
import { GUIDE_STATES, PUBLIC_GUIDES } from "@/lib/publicGuides";

export function siteUrl(configured: string | undefined, host: string | null): string {
  if (configured) return configured.replace(/\/+$/, "");
  return host ? `https://${host}` : "http://localhost:3000";
}

/**
 * The address statically generated pages use for absolute links (structured data, share
 * images): the configured site, or the production domain when building without one.
 */
export const PUBLIC_SITE_URL = siteUrl(process.env.SITE_URL ?? "https://approvalready.au", null);

/**
 * Whether guides go into search before a person has verified their sources. They are shown
 * with every source and the date they were gathered, which is what search engines and answer
 * engines weigh, and they only work as marketing if they can be found (RISKS.md R11).
 */
export const INDEX_UNVERIFIED_GUIDES = true;

export interface SitemapEntry {
  path: string;
  lastModified?: string;
}

/** Public pages for the sitemap. Unverified guides are kept out unless indexing them is on. */
export function sitemapEntries(): SitemapEntry[] {
  const indexed = INDEX_UNVERIFIED_GUIDES;
  const latest = (dates: string[]) => dates.sort().at(-1);
  return [
    { path: "/" },
    { path: "/guides", lastModified: latest(PUBLIC_GUIDES.map((g) => g.checked_on)) },
    ...GUIDES.filter((g) => indexed || g.verification === "VERIFIED").map((g) => ({
      path: `/guides/${g.slug}`,
      lastModified: g.checkedOn,
    })),
    ...(indexed
      ? [
          ...GUIDE_STATES.map((s) => ({
            path: `/guides/${s.segment}`,
            lastModified: latest(
              PUBLIC_GUIDES.filter((g) => g.state.segment === s.segment).map((g) => g.checked_on),
            ),
          })),
          ...PUBLIC_GUIDES.map((g) => ({ path: g.path, lastModified: g.checked_on })),
        ]
      : []),
    { path: "/finance" },
    { path: "/membership" },
    { path: "/newsletter" },
    { path: "/contact" },
    { path: "/privacy" },
    { path: "/terms" },
  ];
}

/** Public page paths for the sitemap. */
export function sitemapPaths(): string[] {
  return sitemapEntries().map((e) => e.path);
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
