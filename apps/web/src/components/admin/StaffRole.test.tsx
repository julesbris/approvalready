import { fireEvent, render, screen } from "@testing-library/react";

import { StaffRole } from "./StaffRole";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

test("the current role is picked and saving waits for a change", () => {
  render(<StaffRole accountId="u1" current="STAFF" />);
  expect(screen.getByLabelText(/^Staff/)).toBeChecked();
  const save = screen.getByRole("button", { name: "Save staff role" });
  expect(save).toBeDisabled();
  fireEvent.click(screen.getByLabelText(/^No staff role/));
  expect(save).toBeEnabled();
});

test("a customer starts with no staff role", () => {
  render(<StaffRole accountId="u1" current={null} />);
  expect(screen.getByLabelText(/^No staff role/)).toBeChecked();
});
