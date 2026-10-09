import type { NotificationOut } from "@approvalready/shared-types";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { NotificationsList } from "./NotificationsList";

const NOTE: NotificationOut = {
  id: "n1",
  kind: "REMINDER",
  title: "Settlement in 2 days",
  body: "12 Example St settles on 14 Oct.",
  link_path: "/projects/p1/sale",
  project_id: "p1",
  email_status: "SENT",
  read_at: null,
  created_at: "2026-10-09T23:00:00Z",
};

describe("NotificationsList", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows an empty state", () => {
    render(<NotificationsList organisationId="o1" initial={{ items: [], unread: 0 }} />);
    expect(screen.getByText(/Nothing yet/)).toBeInTheDocument();
  });

  it("marks everything as read", async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json({ marked: 1 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<NotificationsList organisationId="o1" initial={{ items: [NOTE], unread: 1 }} />);
    expect(screen.getByRole("link", { name: "Settlement in 2 days" })).toHaveAttribute(
      "href",
      "/projects/p1/sale",
    );
    expect(screen.getByText("New")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Mark all as read" }));
    await waitFor(() => expect(screen.queryByText("New")).not.toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Mark all as read" })).not.toBeInTheDocument();
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/organisations/o1/notifications/read-all");
  });
});
