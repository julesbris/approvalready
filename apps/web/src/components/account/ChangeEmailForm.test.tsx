import { fireEvent, render, screen } from "@testing-library/react";

import { ChangeEmailForm } from "./ChangeEmailForm";

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn(), refresh }) }));

const NONE = { pending_email: null, expires_at: null };
const WAITING = { pending_email: "new@example.com", expires_at: "2026-10-11T04:00:00Z" };

describe("ChangeEmailForm", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("asks for the new address and password, then shows the change waiting", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(Response.json(WAITING, { status: 202 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<ChangeEmailForm currentEmail="old@example.com" initial={NONE} mfaEnabled={false} />);
    expect(screen.getByText("old@example.com")).toBeInTheDocument();
    expect(screen.queryByLabelText(/authenticator/)).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("New email address"), {
      target: { value: "new@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Password to confirm it's you"), { target: { value: "pw" } });
    fireEvent.click(screen.getByRole("button", { name: "Change email address" }));
    expect(await screen.findByText(/Check the new inbox/)).toBeInTheDocument();
    expect(screen.getByText("new@example.com")).toBeInTheDocument();
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/auth/email-change");
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({
      new_email: "new@example.com",
      password: "pw",
    });
  });

  it("asks for a code when two-step sign-in is on and cancels a waiting change", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(Response.json(NONE));
    vi.stubGlobal("fetch", fetchMock);
    render(<ChangeEmailForm currentEmail="old@example.com" initial={WAITING} mfaEnabled />);
    expect(screen.getByLabelText(/Code from your authenticator app/)).toBeInTheDocument();
    expect(screen.getByText("new@example.com")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel the change" }));
    expect(await screen.findByText(/Cancelled/)).toBeInTheDocument();
    expect(fetchMock.mock.calls[0]?.[1]?.method).toBe("DELETE");
    expect(screen.queryByText("new@example.com")).not.toBeInTheDocument();
  });
});
