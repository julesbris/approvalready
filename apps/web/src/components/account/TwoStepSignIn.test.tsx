import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { TwoStepSignIn } from "./TwoStepSignIn";

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn(), refresh }) }));

const OFF = { enabled: false, enabled_at: null, recovery_codes_left: 0, required_for_staff: true };
const ON = {
  enabled: true,
  enabled_at: "2026-10-10T04:00:00Z",
  recovery_codes_left: 9,
  required_for_staff: true,
};

describe("TwoStepSignIn", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("sets up an authenticator app and shows the recovery codes once", async () => {
    const setup = { secret: "ABCDEF", otpauth_uri: "otpauth://totp/x", qr_svg: "<svg></svg>" };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(Response.json(setup))
      .mockResolvedValueOnce(Response.json({ recovery_codes: ["aaaa-bbbb-cccc-dddd"] }));
    vi.stubGlobal("fetch", fetchMock);
    render(<TwoStepSignIn status={OFF} />);
    expect(screen.getByText(/Platform staff need it/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Turn on two-step sign-in" }));
    fireEvent.change(screen.getByLabelText("Your password"), { target: { value: "pw" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    const qr = await screen.findByRole("img", { name: /QR code/ });
    expect(qr.getAttribute("src")).toMatch(/^data:image\/svg\+xml/);
    expect(screen.getByText("ABCDEF")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Code from the app"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Turn on" }));
    expect(await screen.findByText("aaaa-bbbb-cccc-dddd")).toBeInTheDocument();
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/v1/auth/mfa/totp/confirm");
    fireEvent.click(screen.getByRole("button", { name: "I've saved them" }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
  });

  it("turns off with the password and a code", async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json(OFF));
    vi.stubGlobal("fetch", fetchMock);
    render(<TwoStepSignIn status={ON} />);
    expect(screen.getByText(/9 recovery codes left/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Turn off" }));
    fireEvent.change(screen.getByLabelText("Your password"), { target: { value: "pw" } });
    fireEvent.change(screen.getByLabelText(/Code from your app/), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Turn off two-step sign-in" }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/auth/mfa/disable");
    expect(JSON.parse(String(init.body))).toEqual({ password: "pw", code: "123456" });
  });
});
