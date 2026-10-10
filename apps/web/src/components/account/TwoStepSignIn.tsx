"use client";

import type { MfaSetupOut, MfaStatusOut, RecoveryCodesOut } from "@approvalready/shared-types";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { FormError, FormNotice } from "@/components/auth/FormStatus";
import { apiRequest } from "@/lib/client-api";
import { formatDate } from "@/lib/questionnaire";

/** The QR code the API drew (an SVG), shown as an image so no markup is injected. */
function qrSource(svg: string): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

function RecoveryCodes({ codes, onDone }: { codes: string[]; onDone: () => void }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(codes.join("\n"));
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }
  return (
    <div className="form">
      <p>
        <strong>Save these recovery codes now.</strong> Each one signs you in once if you lose
        your phone. They won&apos;t be shown again.
      </p>
      <ul className="recovery-codes" aria-label="Recovery codes">
        {codes.map((code) => (
          <li key={code}>
            <code>{code}</code>
          </li>
        ))}
      </ul>
      <div className="button-row">
        <button type="button" className="button button-secondary" onClick={copy}>
          {copied ? "Copied" : "Copy codes"}
        </button>
        <button type="button" className="button" onClick={onDone}>
          I&apos;ve saved them
        </button>
      </div>
    </div>
  );
}

/** Account page: turn two-step sign-in (authenticator app codes) on or off. */
export function TwoStepSignIn({ status }: { status: MfaStatusOut }) {
  const router = useRouter();
  const [setup, setSetup] = useState<MfaSetupOut | null>(null);
  const [askPassword, setAskPassword] = useState(false);
  const [codes, setCodes] = useState<string[] | null>(null);
  const [mode, setMode] = useState<"idle" | "disable" | "regenerate">("idle");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run<T>(path: string, body: unknown, onOk: (data: T) => void): Promise<void> {
    setBusy(true);
    setError(null);
    setNotice(null);
    const result = await apiRequest<T>("POST", path, body);
    setBusy(false);
    if (result.ok) onOk(result.data);
    else setError(result.message);
  }

  function value(event: FormEvent<HTMLFormElement>, name: string): string {
    return String(new FormData(event.currentTarget).get(name) ?? "");
  }

  function finished() {
    setCodes(null);
    setSetup(null);
    setMode("idle");
    router.refresh();
  }

  if (codes) return <RecoveryCodes codes={codes} onDone={finished} />;

  if (!status.enabled) {
    if (setup) {
      return (
        <form
          method="post"
          className="form"
          onSubmit={(e) => {
            e.preventDefault();
            void run<RecoveryCodesOut>(
              "/auth/mfa/totp/confirm",
              { code: value(e, "code") },
              (data) => setCodes(data.recovery_codes),
            );
          }}
        >
          <p>
            Scan this code with an authenticator app (Google Authenticator, Microsoft
            Authenticator, 1Password and others), then enter the 6-digit code it shows.
          </p>
          {/* eslint-disable-next-line @next/next/no-img-element -- an inline data image */}
          <img
            className="qr-code"
            src={qrSource(setup.qr_svg)}
            alt="QR code for your authenticator app"
            width={228}
            height={228}
          />
          <p className="muted">
            Can&apos;t scan it? On this phone, <a href={setup.otpauth_uri}>open it in your app</a>,
            or type this key: <code className="secret-key">{setup.secret}</code>
          </p>
          <label>
            Code from the app
            <input
              name="code"
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              minLength={6}
              maxLength={10}
              required
            />
          </label>
          <FormError message={error} />
          <div className="button-row">
            <button type="submit" className="button" disabled={busy}>
              Turn on
            </button>
            <button
              type="button"
              className="button button-secondary"
              onClick={() => setSetup(null)}
            >
              Cancel
            </button>
          </div>
        </form>
      );
    }
    if (askPassword) {
      return (
        <form
          method="post"
          className="form"
          onSubmit={(e) => {
            e.preventDefault();
            void run<MfaSetupOut>(
              "/auth/mfa/totp/setup",
              { password: value(e, "password") },
              (data) => {
                setSetup(data);
                setAskPassword(false);
              },
            );
          }}
        >
          <label>
            Your password
            <input name="password" type="password" autoComplete="current-password" required />
          </label>
          <FormError message={error} />
          <div className="button-row">
            <button type="submit" className="button" disabled={busy}>
              Continue
            </button>
            <button
              type="button"
              className="button button-secondary"
              onClick={() => setAskPassword(false)}
            >
              Cancel
            </button>
          </div>
        </form>
      );
    }
    return (
      <div className="form">
        <p className="muted">
          Off. With two-step sign-in, signing in also needs a code from an app on your phone,
          so a stolen password alone isn&apos;t enough.
          {status.required_for_staff ? " Platform staff need it to use the admin area." : ""}
        </p>
        <button type="button" className="button" onClick={() => setAskPassword(true)}>
          Turn on two-step sign-in
        </button>
      </div>
    );
  }

  return (
    <div className="form">
      <p>
        <span className="badge">On</span>{" "}
        {status.enabled_at ? `since ${formatDate(status.enabled_at)}. ` : ""}
        {status.recovery_codes_left} recovery code{status.recovery_codes_left === 1 ? "" : "s"}{" "}
        left.
      </p>
      {notice ? <FormNotice>{notice}</FormNotice> : null}
      {mode === "regenerate" ? (
        <form
          method="post"
          className="form"
          onSubmit={(e) => {
            e.preventDefault();
            void run<RecoveryCodesOut>(
              "/auth/mfa/recovery-codes",
              { code: value(e, "code") },
              (data) => setCodes(data.recovery_codes),
            );
          }}
        >
          <label>
            Code from your app
            <input
              name="code"
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              required
            />
          </label>
          <FormError message={error} />
          <div className="button-row">
            <button type="submit" className="button" disabled={busy}>
              Make new recovery codes
            </button>
            <button
              type="button"
              className="button button-secondary"
              onClick={() => setMode("idle")}
            >
              Cancel
            </button>
          </div>
        </form>
      ) : null}
      {mode === "disable" ? (
        <form
          method="post"
          className="form"
          onSubmit={(e) => {
            e.preventDefault();
            void run<MfaStatusOut>(
              "/auth/mfa/disable",
              { password: value(e, "password"), code: value(e, "code") },
              () => finished(),
            );
          }}
        >
          <label>
            Your password
            <input name="password" type="password" autoComplete="current-password" required />
          </label>
          <label>
            Code from your app (or a recovery code)
            <input name="code" type="text" autoComplete="one-time-code" required />
          </label>
          <FormError message={error} />
          <div className="button-row">
            <button type="submit" className="button button-danger" disabled={busy}>
              Turn off two-step sign-in
            </button>
            <button
              type="button"
              className="button button-secondary"
              onClick={() => setMode("idle")}
            >
              Cancel
            </button>
          </div>
        </form>
      ) : null}
      {mode === "idle" ? (
        <div className="button-row">
          <button
            type="button"
            className="button button-secondary"
            onClick={() => setMode("regenerate")}
          >
            New recovery codes
          </button>
          <button
            type="button"
            className="button button-secondary"
            onClick={() => setMode("disable")}
          >
            Turn off
          </button>
        </div>
      ) : null}
    </div>
  );
}
