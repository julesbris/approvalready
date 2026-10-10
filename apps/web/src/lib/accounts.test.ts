import type { AccountEvent, AccountSummary } from "@approvalready/shared-types";

import { ACCOUNT_ACTIONS, accountState, describeDevice, eventBy, eventLabel } from "./accounts";

const account: AccountSummary = {
  id: "u1",
  email: "pat@example.com",
  display_name: "Pat",
  status: "ACTIVE",
  email_verified: true,
  mfa_enabled: false,
  created_at: "2026-10-10T00:00:00Z",
  last_login_at: null,
  closed: false,
  platform_role: null,
  organisations: 1,
};

const event: AccountEvent = {
  seq: 1,
  occurred_at: "2026-10-10T00:00:00Z",
  action: "auth.login.succeeded",
  by: "self",
  actor_email: null,
  ip: null,
  details: {},
};

describe("accounts helpers", () => {
  it("names the account's state", () => {
    expect(accountState(account)).toBe("Active");
    expect(accountState({ ...account, email_verified: false })).toBe("Email not confirmed");
    expect(accountState({ ...account, status: "SUSPENDED" })).toBe("Suspended");
    expect(accountState({ ...account, closed: true, status: "DELETION_REQUESTED" })).toBe("Closed");
  });

  it("labels history and who did it", () => {
    expect(eventLabel("auth.login.succeeded")).toBe("Signed in");
    expect(eventLabel("something.new")).toBe("something.new");
    expect(eventBy(event)).toBe("them");
    expect(eventBy({ ...event, by: "other", actor_email: "staff@example.com" })).toBe(
      "staff@example.com",
    );
    expect(eventBy({ ...event, by: "system" })).toBe("the system");
  });

  it("covers every action the API can offer", () => {
    expect(Object.keys(ACCOUNT_ACTIONS)).toEqual([
      "resend_verification",
      "send_password_reset",
      "sign_out_everywhere",
      "reset_two_step",
      "suspend",
      "restore",
    ]);
    expect(ACCOUNT_ACTIONS.suspend?.needsReason).toBe(true);
  });

  it("recognises common devices", () => {
    const chromeWin =
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) " +
      "Chrome/141.0 Safari/537.36";
    const safariIphone =
      "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 " +
      "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1";
    expect(describeDevice(chromeWin)).toBe("Chrome on Windows");
    expect(describeDevice(safariIphone)).toBe("Safari on iPhone or iPad");
    expect(describeDevice(null)).toBe("Unknown device");
    expect(describeDevice("curl/8.0")).toBe("Unknown device");
  });
});
