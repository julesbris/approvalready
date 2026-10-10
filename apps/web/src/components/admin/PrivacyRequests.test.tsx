import type { PrivacyRequestOut } from "@approvalready/shared-types";
import { render, screen } from "@testing-library/react";

import { PrivacyRequests } from "./PrivacyRequests";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

const CLOSED: PrivacyRequestOut = {
  id: "0192a0b0-0000-7000-8000-00000000abcd",
  user_id: "u1",
  name: "Leaving",
  email: "leaving@example.com",
  kind: "DELETION",
  source: "ACCOUNT_CLOSED",
  details: "The account was closed by its owner.",
  status: "OPEN",
  created_at: "2026-10-10T00:00:00Z",
  due_at: "2026-11-09T00:00:00Z",
  resolved_at: null,
  resolution_note: null,
  overdue: false,
  purged_at: null,
  deletes_on: "2026-10-17T00:00:00Z",
};

test("a closed account waiting to be deleted offers to delete it now", () => {
  render(<PrivacyRequests requests={[CLOSED]} />);
  expect(screen.getByText(/deleted automatically on 17 Oct 2026/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Delete workspace now" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Mark done" })).not.toBeInTheDocument();
});

test("a deleted workspace says when, and a kept one how to delete it", () => {
  render(
    <PrivacyRequests
      requests={[
        {
          ...CLOSED,
          id: "a",
          status: "DONE",
          deletes_on: null,
          purged_at: "2026-10-17T03:20:00Z",
        },
        { ...CLOSED, id: "b", status: "DECLINED", deletes_on: null },
      ]}
    />,
  );
  expect(screen.getByText(/Workspace deleted/)).toBeInTheDocument();
  expect(screen.getByText(/Workspace kept/)).toBeInTheDocument();
});
