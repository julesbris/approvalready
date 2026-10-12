// Hash-based CSP for statically generated pages (Milestone 17).
//
// Static pages (home, guides, not-found) are built once, so they can't carry a per-request
// nonce. Their only inline scripts are the ones Next.js writes into the HTML at build time.
// This runs after `next build`: it hashes every inline script in the prerendered HTML and
// writes them to .next/csp-hashes.json (and into the standalone server's copy), which
// src/proxy.ts puts in those pages' script-src instead of 'unsafe-inline'.
//
// Hashes are listed per page, so each page's policy carries only its own scripts: with a page
// for every guide, one list for all pages would grow to thousands of hashes per response.
// Pages not in the list (not-found pages, for any address) get `scriptHashes`: the scripts
// every page shares plus the not-found and error pages' own. JSON-LD blocks
// (`type="application/ld+json"`) are data, not scripts, so they aren't hashed.
import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

const web = path.resolve(import.meta.dirname, "..");
const pages = path.join(web, ".next", "server", "app");

function htmlFiles(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return htmlFiles(full);
    return entry.name.endsWith(".html") ? [full] : [];
  });
}

const INLINE_SCRIPT = /<script(?![^>]*\bsrc=)(?![^>]*\btype="application\/ld\+json")[^>]*>([\s\S]*?)<\/script>/g;

/** The address a prerendered file is served at ("guides/nsw.html" is "/guides/nsw"). */
function route(file) {
  const rel = path.relative(pages, file).replaceAll(path.sep, "/").replace(/\.html$/, "");
  return rel === "index" ? "/" : `/${rel}`;
}

const perPage = {};
const seen = new Map();
const files = htmlFiles(pages);
for (const file of files) {
  const hashes = new Set();
  for (const match of readFileSync(file, "utf8").matchAll(INLINE_SCRIPT)) {
    if (match[1].length === 0) continue;
    hashes.add(`'sha256-${createHash("sha256").update(match[1], "utf8").digest("base64")}'`);
  }
  if (hashes.size === 0) continue;
  perPage[route(file)] = [...hashes].sort();
  for (const h of hashes) seen.set(h, (seen.get(h) ?? 0) + 1);
}
const routes = Object.keys(perPage);
if (routes.length === 0) {
  console.error("csp-hashes: no prerendered pages with inline scripts found; run next build");
  process.exit(1);
}
const fallback = new Set([...seen].filter(([, n]) => n > 1).map(([h]) => h));
for (const r of routes.filter((r) => r.startsWith("/_"))) {
  for (const h of perPage[r]) fallback.add(h);
}

const manifest =
  JSON.stringify({ scriptHashes: [...fallback].sort(), pages: perPage }, null, 2) + "\n";
const targets = [path.join(web, ".next", "csp-hashes.json")];
const standalone = path.join(web, ".next", "standalone", "apps", "web", ".next");
if (existsSync(standalone)) targets.push(path.join(standalone, "csp-hashes.json"));
for (const target of targets) writeFileSync(target, manifest);
console.log(`csp-hashes: script hashes for ${routes.length} static pages`);
