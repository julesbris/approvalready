// Hash-based CSP for statically generated pages (Milestone 17).
//
// Static pages (home, guides, not-found) are built once, so they can't carry a per-request
// nonce. Their only inline scripts are the ones Next.js writes into the HTML at build time.
// This runs after `next build`: it hashes every inline script in the prerendered HTML and
// writes the list to .next/csp-hashes.json (and into the standalone server's copy), which
// src/proxy.ts puts in those pages' script-src instead of 'unsafe-inline'.
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

const INLINE_SCRIPT = /<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g;

const hashes = new Set();
const files = htmlFiles(pages);
for (const file of files) {
  for (const match of readFileSync(file, "utf8").matchAll(INLINE_SCRIPT)) {
    if (match[1].length === 0) continue;
    hashes.add(`'sha256-${createHash("sha256").update(match[1], "utf8").digest("base64")}'`);
  }
}
if (files.length === 0 || hashes.size === 0) {
  console.error("csp-hashes: no prerendered pages with inline scripts found; run next build");
  process.exit(1);
}

const manifest = JSON.stringify({ scriptHashes: [...hashes].sort() }, null, 2) + "\n";
const targets = [path.join(web, ".next", "csp-hashes.json")];
const standalone = path.join(web, ".next", "standalone", "apps", "web", ".next");
if (existsSync(standalone)) targets.push(path.join(standalone, "csp-hashes.json"));
for (const target of targets) writeFileSync(target, manifest);
console.log(`csp-hashes: ${hashes.size} script hashes from ${files.length} static pages`);
