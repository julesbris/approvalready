import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { LoginForm } from "./LoginForm";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace, refresh: vi.fn() }) }));

function fill() {
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "a@example.com" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "secret" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

describe("LoginForm", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("sends credentials with the CSRF header and redirects on success", async () => {
    document.cookie = "ar_csrf=tok";
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<LoginForm next="/account" />);
    fill();
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/account"));
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/auth/login");
    expect((init.headers as Record<string, string>)["x-csrf-token"]).toBe("tok");
  });

  it("shows the API's message and offers a new link when unverified", async () => {
    const body = { detail: { code: "email_not_verified", message: "Confirm your email first." } };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(body, { status: 403 })));
    render(<LoginForm next="/account" />);
    fill();
    expect(await screen.findByRole("alert")).toHaveTextContent("Confirm your email first.");
    expect(screen.getByRole("button", { name: /new confirmation link/i })).toBeInTheDocument();
  });
});
