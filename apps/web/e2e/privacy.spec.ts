import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

import { loadSeed, signIn } from "./support";

/**
 * Privacy (Milestone 19), in the browser: the legal pages are linked from every page, a
 * visitor makes a privacy request, and a customer downloads their data from the account page.
 * Staff handling of requests needs `privacy.manage` (admins), which the API tests cover.
 */
test("a visitor finds the legal pages and makes a privacy request", async ({ page }) => {
  const seed = loadSeed();
  await page.goto("/");
  const footer = page.getByRole("navigation", { name: "Legal" });
  await footer.getByRole("link", { name: "Privacy Policy" }).click();
  await expect(page.getByRole("heading", { name: "Privacy Policy", level: 1 })).toBeVisible();
  await page
    .getByRole("navigation", { name: "Legal" })
    .getByRole("link", { name: "Contact" })
    .click();
  await expect(page).toHaveURL(/\/contact$/);

  const name = `Visitor ${seed.runId}`;
  await page.getByLabel("Your name").fill(name);
  await page.getByLabel("Email", { exact: true }).fill(`visitor-${seed.runId}@example.com`);
  await page.getByLabel("What would you like?").selectOption("ACCESS");
  await page.getByLabel("Details").fill("Please send me what you hold about me.");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText(/Your reference is/)).toBeVisible();
});

test("a customer downloads their data", async ({ browser }) => {
  const seed = loadSeed();
  const page = await signIn(browser, seed.customer.email, seed.password, "/account");
  await expect(page.getByRole("heading", { name: "Your data", exact: true })).toBeVisible();
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("link", { name: "Download my data" }).click(),
  ]);
  const file = await download.path();
  const data = JSON.parse(readFileSync(file, "utf8")) as { account: { email: string } };
  expect(data.account.email).toBe(seed.customer.email);
  await page.context().close();
});
