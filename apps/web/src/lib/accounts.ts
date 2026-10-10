/** Staff accounts page (Milestone 27): labels and small helpers. */

import type { AccountEvent, AccountSummary } from "@approvalready/shared-types";

export const ACCOUNT_FILTERS = [
  ["", "All accounts"],
  ["ACTIVE", "Active"],
  ["UNVERIFIED", "Email not confirmed"],
  ["SUSPENDED", "Suspended"],
  ["STAFF", "Staff"],
  ["CLOSED", "Closed"],
] as const;

/** One plain-language state for an account, most important first. */
export function accountState(account: AccountSummary): string {
  if (account.closed) return "Closed";
  if (account.status === "SUSPENDED") return "Suspended";
  if (account.status === "LOCKED") return "Locked";
  if (!account.email_verified) return "Email not confirmed";
  return "Active";
}

type ActionInfo = { label: string; help: string; confirm: string; needsReason?: boolean };

/** Support actions, in the order the API lists them. */
export const ACCOUNT_ACTIONS: Record<string, ActionInfo> = {
  resend_verification: {
    label: "Resend verification email",
    help: "Sends a new link to confirm their email address. Older links stop working.",
    confirm: "Send a new verification email?",
  },
  send_password_reset: {
    label: "Send password reset link",
    help: "Emails them a link to choose a new password. You never see or set the password.",
    confirm: "Email a password reset link?",
  },
  sign_out_everywhere: {
    label: "Sign out everywhere",
    help: "Ends every signed-in session, for example after a lost or shared device.",
    confirm: "Sign this person out on every device?",
  },
  reset_two_step: {
    label: "Reset two-step sign-in",
    help:
      "For a lost phone and lost recovery codes. Turns two-step sign-in off and signs them " +
      "out; they can then sign in with their password and set it up again. Only do this " +
      "after confirming who you are talking to.",
    confirm: "Turn off two-step sign-in for this account?",
    needsReason: true,
  },
  suspend: {
    label: "Suspend account",
    help:
      "Signs them out and stops them signing in until restored. Their data is kept. " +
      "Other members of their businesses are not affected.",
    confirm: "Suspend this account?",
    needsReason: true,
  },
  restore: {
    label: "Restore account",
    help: "Lets them sign in again.",
    confirm: "Restore this account?",
  },
};

const EVENT_LABELS: Record<string, string> = {
  "auth.registered": "Signed up",
  "auth.email_verified": "Confirmed their email address",
  "auth.login.succeeded": "Signed in",
  "auth.login.failed": "Failed sign-in",
  "auth.login.mfa_challenged": "Entered their password (code asked for)",
  "auth.mfa.failed": "Wrong two-step code",
  "auth.mfa.setup_started": "Started setting up two-step sign-in",
  "auth.logout": "Signed out",
  "auth.logout_all": "Signed out everywhere",
  "auth.password_reset.requested": "Asked for a password reset",
  "auth.password_reset.completed": "Reset their password",
  "auth.password.changed": "Changed their password",
  "auth.mfa.enabled": "Turned on two-step sign-in",
  "auth.mfa.disabled": "Turned off two-step sign-in",
  "auth.mfa.reset": "Two-step sign-in reset",
  "auth.mfa.recovery_codes_regenerated": "Made new recovery codes",
  "auth.session.organisation_switched": "Switched organisation",
  "org.created": "Created an organisation",
  "org.updated": "Edited an organisation",
  "privacy.data_exported": "Downloaded their data",
  "privacy.policies.accepted": "Agreed to the Terms and Privacy Policy",
  "project.created": "Started a project",
  "project.status_changed": "Changed a project's status",
  "questionnaire.started": "Started a questionnaire",
  "questionnaire.submitted": "Submitted a questionnaire",
  "assessment.run": "Ran an assessment",
  "account.closed": "Closed their account",
  "admin.account.verification_resent": "Verification email resent",
  "admin.account.password_reset_sent": "Password reset link sent",
  "admin.account.signed_out": "Signed out everywhere",
  "admin.account.suspended": "Account suspended",
  "admin.account.restored": "Account restored",
  "platform.role_granted": "Given a staff role",
};

/** "Signed in", falling back to the raw action name for anything not listed. */
export function eventLabel(action: string): string {
  return EVENT_LABELS[action] ?? action;
}

/** Who did it, for the history list. */
export function eventBy(event: AccountEvent): string {
  if (event.by === "self") return "them";
  if (event.by === "system") return "the system";
  return event.actor_email ?? "someone else";
}

/** "Chrome on Windows" from a user agent, good enough to recognise a device. */
export function describeDevice(userAgent: string | null): string {
  if (!userAgent) return "Unknown device";
  const browser = /Edg\//.test(userAgent)
    ? "Edge"
    : /Firefox\//.test(userAgent)
      ? "Firefox"
      : /Chrome\//.test(userAgent)
        ? "Chrome"
        : /Safari\//.test(userAgent)
          ? "Safari"
          : null;
  const system = /iPhone|iPad/.test(userAgent)
    ? "iPhone or iPad"
    : /Android/.test(userAgent)
      ? "Android"
      : /Windows/.test(userAgent)
        ? "Windows"
        : /Mac OS X|Macintosh/.test(userAgent)
          ? "Mac"
          : /Linux/.test(userAgent)
            ? "Linux"
            : null;
  if (browser && system) return `${browser} on ${system}`;
  return browser ?? system ?? "Unknown device";
}
