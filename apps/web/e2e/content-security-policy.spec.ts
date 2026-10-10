import { expect, test } from "@playwright/test";

/**
 * Content Security Policy (Milestone 17): static pages run only the inline scripts hashed at
 * build time (scripts/csp-hashes.mjs) and signed-in pages only nonce'd scripts. Any script the
 * policy blocks shows up as a console error, and the page would stop working in the browser.
 */

const STATIC_PAGES = ["/", "/guides", "/guides/cairns-secondary-dwellings", "/no-such-page"];
const DYNAMIC_PAGES = ["/login", "/register", "/partner/apply"];

test("pages run without Content Security Policy violations", async ({ page }) => {
  const violations: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" && /Content Security Policy/i.test(message.text())) {
      violations.push(`${page.url()}: ${message.text()}`);
    }
  });

  for (const path of STATIC_PAGES) {
    const response = await page.goto(path);
    const csp = (await response?.headerValue("content-security-policy")) ?? "";
    const scripts = csp.split("; ").find((d) => d.startsWith("script-src")) ?? "";
    expect(scripts, path).toContain("'sha256-");
    expect(scripts, path).not.toContain("unsafe-inline");
    await page.waitForLoadState("networkidle");
  }
  for (const path of DYNAMIC_PAGES) {
    const response = await page.goto(path);
    const csp = (await response?.headerValue("content-security-policy")) ?? "";
    expect(csp, path).toContain("'nonce-");
    expect(csp, path).not.toContain("script-src 'self' 'unsafe-inline'");
    await page.waitForLoadState("networkidle");
  }

  // Client-side navigation from a static page into the app keeps working.
  await page.goto("/guides");
  await page.getByRole("link").first().click();
  await page.waitForLoadState("networkidle");

  expect(violations).toEqual([]);
});
