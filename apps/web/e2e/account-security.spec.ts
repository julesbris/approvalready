import { expect, test } from "@playwright/test";

import { loadSeed, signIn, totpCode } from "./support";

/**
 * Two-step sign-in (Milestone 18), in the browser: a customer turns it on from the account
 * page with an authenticator code, keeps the recovery codes, and from then on signing in
 * needs a code after the password.
 */
test("a customer turns on two-step sign-in and signs in with a code", async ({ browser }) => {
  const seed = loadSeed();
  const page = await signIn(browser, seed.security.email, seed.password, "/account");

  await page.getByRole("button", { name: "Turn on two-step sign-in" }).click();
  await page.getByLabel("Your password").fill(seed.password);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("img", { name: /QR code/ })).toBeVisible();
  const secret = (await page.locator(".secret-key").textContent())?.trim() ?? "";
  expect(secret).toMatch(/^[A-Z2-7]{32}$/);
  await page.getByLabel("Code from the app").fill(totpCode(secret, 0));
  await page.getByRole("button", { name: "Turn on" }).click();
  const codes = page.getByRole("list", { name: "Recovery codes" }).getByRole("listitem");
  await expect(codes).toHaveCount(10);
  await page.getByRole("button", { name: "I've saved them" }).click();
  await expect(page.getByText(/10 recovery codes left/)).toBeVisible();

  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(/\/login/);
  await page.context().close();

  // Signing in again takes the password, then a code from the app.
  const again = await signIn(browser, seed.security.email, seed.password, "/account", secret);
  await expect(again.getByText(/10 recovery codes left/)).toBeVisible();
});
