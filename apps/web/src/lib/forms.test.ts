import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";

/**
 * Every form is handled in the browser (onSubmit), but one submitted before the page's
 * scripts load falls back to the browser default, GET, which would put passwords and other
 * answers in the address and in server logs. method="post" keeps them in the request body
 * (found by the ZAP baseline scan, Milestone 17).
 */
function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return sources(full);
    return entry.name.endsWith(".tsx") && !entry.name.endsWith(".test.tsx") ? [full] : [];
  });
}

describe("forms", () => {
  it("all post, so nothing typed into them can end up in a URL", () => {
    const src = path.resolve(import.meta.dirname, "..");
    const offenders: string[] = [];
    for (const file of sources(src)) {
      for (const match of readFileSync(file, "utf8").matchAll(/<form\b[^>]*>/g)) {
        if (!/method="post"/.test(match[0])) offenders.push(path.relative(src, file));
      }
    }
    expect(offenders).toEqual([]);
  });
});
