import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { NotificationPreferences } from "./NotificationPreferences";
import { Unsubscribe } from "./Unsubscribe";

const PREFS = {
  items: [
    { category: "REMINDERS", channel: "ALL" },
    { category: "GRANT_ROUNDS", channel: "ALL" },
    { category: "REFERRALS", channel: "ALL" },
    { category: "SOURCE_REVIEWS", channel: "ALL" },
  ],
} as const;

describe("NotificationPreferences", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("saves the chosen channel for each category", async () => {
    const fetchMock = vi.fn().mockImplementation((_url: string, init: RequestInit) =>
      Promise.resolve(Response.json({ items: JSON.parse(String(init.body)).items })),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<NotificationPreferences initial={{ items: [...PREFS.items] }} isStaff={false} />);
    expect(screen.queryByLabelText(/Source reviews/)).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/^Reminders/), { target: { value: "IN_APP" } });
    fireEvent.click(screen.getByRole("button", { name: "Save notification settings" }));
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/auth/notification-preferences");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(String(init.body)).items[0]).toEqual({
      category: "REMINDERS",
      channel: "IN_APP",
    });
  });
});

describe("Unsubscribe", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("waits for a click before stopping emails", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(Response.json({ category: "GRANT_ROUNDS", channel: "ALL" }))
      .mockResolvedValueOnce(Response.json({ scope: "category", items: [] }));
    vi.stubGlobal("fetch", fetchMock);
    render(<Unsubscribe token="abc.GRANT_ROUNDS.sig" />);
    const button = await screen.findByRole("button", { name: "Stop grant rounds emails" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    fireEvent.click(button);
    expect(await screen.findByText(/won't get grant rounds emails/)).toBeInTheDocument();
    await waitFor(() =>
      expect(fetchMock.mock.calls[1]?.[0]).toBe(
        "/api/v1/auth/unsubscribe?token=abc.GRANT_ROUNDS.sig&scope=category",
      ),
    );
  });

  it("explains a link that doesn't work", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        Response.json(
          { detail: { code: "invalid_link", message: "This unsubscribe link doesn't work." } },
          { status: 400 },
        ),
      ),
    );
    render(<Unsubscribe token="bad" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("doesn't work");
  });
});
