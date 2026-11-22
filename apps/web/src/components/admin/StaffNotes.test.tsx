import type { StaffNoteOut } from "@approvalready/shared-types";
import { fireEvent, render, screen } from "@testing-library/react";

import { EmailCustomer, StaffNotes } from "./StaffNotes";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

const EMAIL: StaffNoteOut = {
  id: "n1",
  kind: "EMAIL",
  subject: "Can we help with PLN-ABC123?",
  body: "Happy to walk you through it.",
  project_reference: "PLN-ABC123",
  created_at: "2026-11-21T00:00:00Z",
  author_name: "Sam Support",
  can_delete: false,
};

test("notes show what kind they are, who wrote them and only allowed deletes", () => {
  render(
    <StaffNotes
      accountId="u1"
      canAdd
      project={null}
      notes={[EMAIL, { ...EMAIL, id: "n2", kind: "CALL", subject: null, can_delete: true }]}
    />,
  );
  expect(screen.getByText("Email sent")).toBeInTheDocument();
  expect(screen.getByText("Subject: Can we help with PLN-ABC123?")).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "Delete" })).toHaveLength(1);
  fireEvent.click(screen.getByLabelText("A phone call and how it went"));
  expect(screen.getByRole("button", { name: "Log call" })).toBeInTheDocument();
});

test("closed accounts show notes without the form", () => {
  render(<StaffNotes accountId="u1" canAdd={false} project={null} notes={[]} />);
  expect(screen.getByText("No notes yet.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Save note" })).not.toBeInTheDocument();
});

test("the email form starts from the stuck-project draft", () => {
  render(
    <EmailCustomer
      accountId="u1"
      email="robin@example.com"
      project="PLN-ABC123"
      draft={{ subject: "Can we help with PLN-ABC123?", message: "Hello" }}
    />,
  );
  expect(screen.getByLabelText("Subject")).toHaveValue("Can we help with PLN-ABC123?");
  expect(screen.getByLabelText("Project (optional)")).toHaveValue("PLN-ABC123");
  expect(screen.getByText(/Goes to robin@example.com/)).toBeInTheDocument();
});
