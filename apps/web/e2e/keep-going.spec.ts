import { expect, test } from "@playwright/test";

import { loadSeed, signIn } from "./support";

/**
 * Keep going (Milestone 30), in the browser: a new project shows what's left, first step
 * first, and the link takes the customer straight to it. The reminder emails and the staff
 * Stuck projects page are covered by the API tests (they depend on days passing).
 */
test("a new project shows what's left and links straight to it", async ({ browser }) => {
  const seed = loadSeed();
  const page = await signIn(browser, seed.customer.email, seed.password, "/projects/new?vertical=PLANNING");
  await page.getByLabel("Project name").fill(`Shed ${seed.runId}`);
  await page.getByRole("button", { name: "Create project" }).click();
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+$/);

  const panel = page.getByRole("region", { name: "What's left" });
  const first = panel.getByRole("link", { name: "Answer the questions about your project" });
  await expect(first).toBeVisible();
  await panel.getByRole("link", { name: "Pick up where you left off" }).click();
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+\/questionnaire$/);
});
