import type { SessionOut } from "@approvalready/shared-types";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { AdminNoAccess } from "./AppShell";

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));

const PERSONAL = { organisation_id: "o-personal", kind: "PERSONAL", name: "Jo", roles: ["OWNER"] };
const PLATFORM = {
  organisation_id: "o-platform",
  kind: "PLATFORM_ADMIN",
  name: "ApprovalReady",
  roles: ["SUPERADMIN"],
};

function session(organisations: SessionOut["organisations"]): SessionOut {
  return {
    active_organisation_id: "o-personal",
    csrf_token: "t",
    expires_at: "2026-10-11T00:00:00Z",
    idle_expires_at: "2026-10-10T12:00:00Z",
    organisations,
    permissions: [],
    staff_mfa_required: false,
    user: {
      id: "u1",
      display_name: "Jo",
      email: "jo@example.com",
      email_verified: true,
      mfa_enabled: false,
    },
  };
}

describe("AdminNoAccess", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("offers the switch when the platform organisation isn't active", async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json({}));
    vi.stubGlobal("fetch", fetchMock);
    render(<AdminNoAccess what="operations" session={session([PERSONAL, PLATFORM])} />);
    expect(screen.getByText(/You're working in Jo/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Switch to ApprovalReady" }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/auth/session/organisation");
  });

  it("says plainly when the account has no platform role", () => {
    render(<AdminNoAccess what="operations" session={session([PERSONAL])} />);
    expect(screen.getByText("No access to operations")).toBeInTheDocument();
    expect(screen.getByText(/isn't on the ApprovalReady team/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("asks staff to turn on two-step sign-in", () => {
    const s = {
      ...session([PERSONAL, PLATFORM]),
      active_organisation_id: "o-platform",
      staff_mfa_required: true,
    };
    render(<AdminNoAccess what="operations" session={s} />);
    expect(screen.getByText("Turn on two-step sign-in to open operations")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Turn it on in your account" })).toHaveAttribute(
      "href",
      "/account#security",
    );
  });

  it("falls back to the role message inside the platform organisation", () => {
    const s = { ...session([PERSONAL, PLATFORM]), active_organisation_id: "o-platform" };
    render(<AdminNoAccess what="operations" session={s} />);
    expect(screen.getByText(/ask an administrator of this organisation/)).toBeInTheDocument();
  });
});
