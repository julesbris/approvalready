import { createHmac } from "node:crypto";
import { readFileSync } from "node:fs";

import { type Browser, expect, type Page } from "@playwright/test";

/** What scripts/e2e.sh seed wrote (apps/api/scripts/e2e_stack.py). */
export type Seed = {
  runId: string;
  password: string;
  platformOrganisation: string;
  staff: { email: string; totpSecret: string };
  security: { email: string };
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

/**
 * The authenticator app code (RFC 6238: HMAC-SHA1, 6 digits, 30 s) for a base32 secret, one
 * step ahead by default: the API accepts one step of drift either way, and a code from the
 * step the seed or an earlier sign-in already used is refused (no replays).
 */
export function totpCode(secret: string, stepOffset = 1): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const ch of secret.toUpperCase().replace(/=+$/, "")) {
    bits += alphabet.indexOf(ch).toString(2).padStart(5, "0");
  }
  const key = Buffer.from(
    (bits.match(/.{8}/g) ?? []).map((byte) => Number.parseInt(byte, 2)),
  );
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30_000) + stepOffset));
  const digest = createHmac("sha1", key).update(counter).digest();
  const offset = (digest[digest.length - 1] ?? 0) & 0x0f;
  const value = digest.readUInt32BE(offset) & 0x7fffffff;
  return String(value % 1_000_000).padStart(6, "0");
}

/**
 * A separate browser (own cookies) signed in as `email`, landing on `next`. With
 * `totpSecret`, the two-step sign-in code is entered too.
 */
export async function signIn(
  browser: Browser,
  email: string,
  password: string,
  next: string,
  totpSecret?: string,
): Promise<Page> {
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto(`/login?next=${encodeURIComponent(next)}`);
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  if (totpSecret) {
    await page.getByLabel("Code", { exact: true }).fill(totpCode(totpSecret));
    await page.getByRole("button", { name: "Continue" }).click();
  }
  await expect(page).toHaveURL((url) => url.pathname === next.split("?")[0]);
  return page;
}
