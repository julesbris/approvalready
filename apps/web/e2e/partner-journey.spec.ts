import { expect, test } from "@playwright/test";

import { loadSeed, signIn } from "./support";

/**
 * The partner journey (Milestone 15) in the browser: the same steps as
 * apps/api/tests/test_leads.py::test_partner_journey, through the UI. A partner business
 * applies, platform staff check and approve it, a customer whose assessment names the
 * partner's categories asks to be introduced, and the partner sees the offer, accepts it,
 * gets the contact details and records the outcome; the customer sees who accepted.
 *
 * The accounts, staff roles, the rule and the customer's assessed project are seeded by
 * scripts/e2e.sh (apps/api/scripts/e2e_stack.py); everything below happens in the browser.
 */

const seed = loadSeed();
const business = seed.partner.business;
const BUSINESS_PHONE = "(07) 4000 0000";

test("partner journey: apply, approve, introduce, accept, outcome", async ({ browser }) => {
  const partner = await signIn(browser, seed.partner.email, seed.password, "/partner/apply");

  await test.step("a partner business applies through the partner portal", async () => {
    const page = partner;
    await expect(page.getByRole("heading", { name: "Apply to become a partner" })).toBeVisible();

    await page.getByLabel("Business name", { exact: true }).fill(business);
    await page.getByLabel("ABN", { exact: true }).fill("51 824 753 556");
    await page
      .getByLabel("Website (optional)", { exact: true })
      .fill("reefcertifiers.example.com.au");
    await page.getByLabel("Phone for customers (optional)", { exact: true }).fill(BUSINESS_PHONE);
    await page
      .getByLabel("Email for customers (optional)", { exact: true })
      .fill("hello@reefcertifiers.example.com.au");
    await page
      .getByLabel("What your business does", { exact: true })
      .fill("Building certification and town planning for homes in Cairns.");
    await page.getByRole("checkbox", { name: /Building certifier/ }).check();
    await page.getByRole("checkbox", { name: /Town planner/ }).check();

    const areas = page.getByRole("region", { name: "Where you work" });
    await areas.getByRole("textbox", { name: "Council area", exact: true }).fill("Cairns");
    await areas.getByRole("button", { name: "Add area" }).click();
    await areas.getByRole("combobox", { name: /Kind of area/ }).selectOption("POSTCODE");
    await areas.getByRole("textbox", { name: "Postcode", exact: true }).fill("4870");
    await areas.getByRole("button", { name: "Add area" }).click();
    await expect(areas.getByRole("list", { name: "Your service areas" })).toContainText(
      "Cairns (council area, QLD)",
    );
    await expect(areas.getByRole("list", { name: "Your service areas" })).toContainText(
      "4870 QLD",
    );

    const credentials = page.getByRole("region", { name: "Licences and insurance" });
    await credentials.getByRole("textbox", { name: "Issued by" }).fill("QBCC");
    await credentials.getByRole("textbox", { name: "Number", exact: true }).fill("1234567");
    await credentials.getByLabel("Expires (if it does)", { exact: true }).fill("2099-06-30");
    await credentials.getByRole("checkbox", { name: "Building certifier" }).check();
    await credentials.getByRole("button", { name: "Add credential" }).click();
    await credentials.getByRole("combobox").selectOption("PI_INSURANCE");
    await credentials.getByRole("textbox", { name: "Insurer" }).fill("Example Insurance");
    await credentials.getByRole("textbox", { name: "Policy number" }).fill("PI-42");
    await credentials.getByRole("textbox", { name: "Cover ($)" }).fill("2000000");
    await credentials.getByLabel("Expires (if it does)", { exact: true }).fill("2099-01-31");
    await credentials.getByRole("button", { name: "Add credential" }).click();
    const added = credentials.getByRole("list", { name: "Your credentials" });
    await expect(added.getByRole("listitem")).toHaveCount(2);
    await expect(added).toContainText("QBCC 1234567. Covers Building certifier");

    await page.getByRole("checkbox", { name: /The details above are true/ }).check();
    await page.getByRole("button", { name: "Send application" }).click();
    await expect(page).toHaveURL(/\/partner\?applied=1$/);
    await expect(page.getByText("Thanks, we have your application.")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Partner dashboard" })).toBeVisible();
  });

  await test.step("platform staff check the credentials and approve the partner", async () => {
    const page = await signIn(
      browser,
      seed.staff.email,
      seed.password,
      "/projects",
      seed.staff.totpSecret,
    );
    // Staff sign in to their personal organisation; switch to the platform organisation.
    const switched = page.waitForResponse(
      (r) => r.url().endsWith("/api/v1/auth/session/organisation") && r.ok(),
    );
    await page
      .getByRole("combobox", { name: "Active organisation" })
      .selectOption({ label: seed.platformOrganisation });
    await switched;
    await page.goto("/admin/partners?status=APPLIED");
    await expect(page.getByRole("heading", { name: "Partners", level: 1 })).toBeVisible();
    const applied = page.getByRole("list", { name: "Partners" });
    await applied.getByRole("link", { name: business, exact: true }).click();
    await expect(page.getByRole("heading", { level: 1 })).toContainText(business);

    const credentials = page.getByRole("list", { name: "Credentials" });
    for (const credential of ["QBCC 1234567", "Example Insurance PI-42"]) {
      const item = credentials.getByRole("listitem").filter({ hasText: credential });
      await item.getByRole("button", { name: "Mark checked" }).click();
      await expect(item.getByRole("button", { name: "Mark checked" })).toHaveCount(0);
      await expect(item).toContainText("Checked");
    }

    const categories = page.getByRole("list", { name: "Categories" });
    for (const category of ["Building certifier", "Town planner"]) {
      const item = categories.getByRole("listitem").filter({ hasText: category });
      await item.getByRole("button", { name: "Approve", exact: true }).click();
      await expect(item.getByRole("button", { name: "Approve", exact: true })).toHaveCount(0);
      await expect(item).toContainText("Approved");
    }

    const status = page.getByRole("region", { name: "Business" });
    await status.getByRole("button", { name: "Approve", exact: true }).click();
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Approved");
    await expect(status.getByText("Receiving referrals.")).toBeVisible();
    await page.context().close();
  });

  const customer = await signIn(
    browser,
    seed.customer.email,
    seed.password,
    `/projects/${seed.projectId}/assessments/${seed.assessmentId}`,
  );

  await test.step("the customer asks to be introduced to a town planner", async () => {
    const page = customer;
    await page.getByRole("link", { name: "Introduce me to checked partners" }).click();
    await expect(page.getByRole("heading", { name: "Introductions to partners" })).toBeVisible();

    await page.getByRole("checkbox", { name: /Town planner/ }).check();
    await expect(page.getByRole("checkbox", { name: /Building certifier/ })).not.toBeChecked();
    await page
      .getByLabel("Describe the job in a sentence or two (optional)")
      .fill("One-bedroom granny flat behind the house, about 92 square metres.");
    await page.getByLabel("Suburb (optional)", { exact: true }).fill("Edge Hill");
    await page
      .getByLabel("Council area (optional)", { exact: true })
      .fill("Cairns Regional Council");
    await page.getByLabel("Postcode", { exact: true }).fill("4870");
    // Name and phone are shared on accepting (the defaults); email and address are not.
    await expect(page.getByRole("textbox", { name: "Your name", exact: true })).toHaveValue(
      seed.customer.name,
    );
    await page.getByRole("textbox", { name: "Phone", exact: true }).fill(seed.customer.phone);
    await expect(page.getByRole("checkbox", { name: "Email", exact: true })).not.toBeChecked();
    await expect(page.getByText("Partners do not pay to rank higher")).toBeVisible();
    await page.getByRole("checkbox", { name: /I agree/ }).check();
    await page.getByRole("button", { name: "Introduce me" }).click();

    await expect(page).toHaveURL(/\/referrals\?sent=1$/);
    await expect(page.getByText("We're offering your request")).toBeVisible();
    const request = page.getByRole("region", { name: "Town planner" });
    await expect(request).toContainText("Finding partners");
    await expect(request).toContainText("0 of 2 accepted");
  });

  await test.step("the partner sees the offer, without the customer's details", async () => {
    const page = partner;
    await page.goto("/partner/leads");
    const waiting = page.getByRole("region", { name: "Waiting for you" });
    // The worker matches the request (the leads.match task): reload until it is offered.
    await expect(async () => {
      await page.reload();
      await expect(waiting.getByRole("link", { name: "Town planner" })).toBeVisible({
        timeout: 1_000,
      });
    }).toPass({ timeout: 60_000 });
    await expect(waiting).toContainText("Edge Hill, Cairns Regional Council QLD 4870");
    await expect(waiting).toContainText("New");

    await waiting.getByRole("link", { name: "Town planner" }).click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Town planner Viewed");
    const job = page.getByRole("region", { name: "The job" });
    await expect(job).toContainText("A development application is likely");
    await expect(job).toContainText("One-bedroom granny flat");
    await expect(page.getByRole("region", { name: /Why you were matched/ })).toContainText(
      "Works in this postcode",
    );
    await expect(page.getByText(seed.customer.name)).toHaveCount(0);
    await expect(page.getByText(seed.customer.phone)).toHaveCount(0);
  });

  await test.step("the partner accepts and gets the contact details", async () => {
    const page = partner;
    await page.getByRole("button", { name: "Accept", exact: true }).click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Town planner Accepted");
    const contact = page.getByRole("region", { name: "Contact details" });
    await expect(contact).toContainText(seed.customer.name);
    await expect(contact).toContainText(seed.customer.phone);
    await expect(contact).toContainText("Included in your plan.");
    await expect(contact).not.toContainText(seed.customer.email);
  });

  await test.step("the partner records contacting, quoting and winning the work", async () => {
    const page = partner;
    const outcome = page.getByRole("region", { name: "What happened?" });
    for (const step of ["Contacted", "Quoted", "Won"]) {
      await outcome.getByRole("button", { name: step, exact: true }).click();
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(`Town planner ${step}`);
    }
    await expect(outcome).toHaveCount(0);
    await page.goto("/partner/leads");
    await expect(page.getByRole("region", { name: "Waiting for you" })).toContainText(
      "No new referrals right now.",
    );
  });

  await test.step("the customer sees who accepted", async () => {
    const page = customer;
    await page.goto(`/projects/${seed.projectId}/referrals`);
    const request = page.getByRole("region", { name: "Town planner" });
    await expect(request).toContainText(`${business} accepted`);
    await expect(request).toContainText(BUSINESS_PHONE);
    await expect(request).toContainText("1 of 2 accepted");
  });
});
