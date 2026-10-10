import { defineConfig, devices } from "@playwright/test";

/**
 * Browser end-to-end tests against a running stack. Start it and seed it with
 * scripts/e2e.sh (`scripts/e2e.sh run` does everything); this config only drives the browser.
 */
const executablePath = process.env.E2E_CHROMIUM_PATH || undefined;

export default defineConfig({
  testDir: ".",
  testMatch: "**/*.spec.ts",
  // One journey across several people's browsers, against one shared database.
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: Boolean(process.env.CI),
  timeout: 120_000,
  expect: { timeout: 15_000 },
  outputDir: "test-results",
  reporter: [
    ["list"],
    ["html", { outputFolder: "playwright-report", open: "never" }],
  ],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    // Only for a local Chromium that doesn't match this Playwright version's build.
    launchOptions: executablePath ? { executablePath } : {},
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
