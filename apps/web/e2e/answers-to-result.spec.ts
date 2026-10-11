import { expect, test } from "@playwright/test";

import { loadSeed, signIn } from "./support";

/**
 * From a new project to its result on one page: the questions one section at a time with one
 * main button, and the last section's button shows the assessment right under the answers.
 */
test("a customer answers the questions and sees the result under them", async ({ browser }) => {
  const seed = loadSeed();
  const page = await signIn(browser, seed.customer.email, seed.password, "/projects/new?vertical=PLANNING");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+\/questionnaire$/);

  // The site. With the address search on offer, the typed-in fields wait until asked for.
  await expect(page.getByText("Step 1 of 4")).toBeVisible();
  await page.getByRole("button", { name: "Can't find it? Type the address in" }).click();
  await page.getByLabel("Street address").fill("1 Example St");
  await page.getByLabel("Suburb or town").fill("Edge Hill");
  await page.getByLabel("State").selectOption("QLD");
  await page.getByLabel("Postcode").fill("4870");
  await page.getByLabel(/Lot and plan/).fill(`LOT_E2E_${seed.runId}`);
  await page.getByLabel(/Land area/).fill("812");
  await page.getByRole("group", { name: "Is there an existing house on the land?" })
    .getByLabel("Yes")
    .check();
  await page.getByRole("button", { name: "Continue" }).click();

  // What they want to do.
  await expect(page.getByText(/Step 2 of 4/)).toBeVisible();
  await page.getByLabel("A secondary dwelling (granny flat)").check();
  await page.getByLabel("How many bedrooms would the secondary dwelling have?").fill("1");
  await page.getByLabel(/Approximate floor area/).fill("92.5");
  await page.getByLabel("How many storeys will the building have?").fill("1");
  await page.getByRole("button", { name: "Continue" }).click();

  // Nothing else is required: straight through to the result.
  await expect(page.getByText(/Step 3 of 4/)).toBeVisible();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText(/Step 4 of 4/)).toBeVisible();
  await page.getByRole("button", { name: "See my result" }).click();

  await expect(page.getByRole("heading", { level: 1, name: "Your result" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Open your full report" })).toBeVisible();
  await expect(page.getByRole("region", { name: "What you may need to do" })).toBeVisible();
  // Still on the questions page: no separate submit, run and report steps.
  await expect(page).toHaveURL(/\/questionnaire$/);
});
