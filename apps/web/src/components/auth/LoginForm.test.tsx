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

describe("LoginForm with two-step sign-in", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("asks for a code after the password, then signs in", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(Response.json({ mfa_required: true }))
      .mockResolvedValueOnce(Response.json({}));
    vi.stubGlobal("fetch", fetchMock);
    render(<LoginForm next="/admin" />);
    fill();
    const code = await screen.findByLabelText("Code");
    expect(code).toHaveAttribute("autocomplete", "one-time-code");
    fireEvent.change(code, { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/admin"));
    const [url, init] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(url).toBe("/api/v1/auth/login/mfa");
    expect(JSON.parse(String(init.body))).toEqual({ code: "123456" });
  });

  it("goes back to the password when the code step has timed out", async () => {
    const expired = {
      detail: { code: "mfa_challenge_expired", message: "Your sign-in timed out." },
    };
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(Response.json({ mfa_required: true }))
        .mockResolvedValueOnce(Response.json(expired, { status: 401 })),
    );
    render(<LoginForm next="/account" />);
    fill();
    fireEvent.change(await screen.findByLabelText("Code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Your sign-in timed out.");
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
  });
});
