import { readFileSync } from "node:fs";

import { type Browser, expect, type Page } from "@playwright/test";

/** What scripts/e2e.sh seed wrote (apps/api/scripts/e2e_stack.py). */
export type Seed = {
  runId: string;
  password: string;
  platformOrganisation: string;
  staff: { email: string };
  partner: { email: string; business: string };
  customer: { email: string; name: string; phone: string };
  projectId: string;
  assessmentId: string;
};

export function loadSeed(): Seed {
  const file = process.env.E2E_SEED_FILE;
  if (!file) {
    throw new Error("E2E_SEED_FILE is not set: run the suite with scripts/e2e.sh test");
  }
  return JSON.parse(readFileSync(file, "utf8")) as Seed;
}

/** A separate browser (own cookies) signed in as `email`, landing on `next`. */
export async function signIn(
  browser: Browser,
  email: string,
  password: string,
  next: string,
): Promise<Page> {
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto(`/login?next=${encodeURIComponent(next)}`);
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL((url) => url.pathname === next.split("?")[0]);
  return page;
}
