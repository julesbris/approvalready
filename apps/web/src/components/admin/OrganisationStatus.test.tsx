import { fireEvent, render, screen } from "@testing-library/react";

import { OrganisationStatus } from "./OrganisationStatus";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

test("suspending needs a reason first", () => {
  render(<OrganisationStatus accountId="u1" organisationId="o1" name="Reef Co" status="ACTIVE" />);
  fireEvent.click(screen.getByRole("button", { name: "Suspend workspace" }));
  expect(screen.getByText(/Say why first/)).toBeInTheDocument();
});

test("a suspended workspace offers to restore it", () => {
  render(
    <OrganisationStatus accountId="u1" organisationId="o1" name="Reef Co" status="SUSPENDED" />,
  );
  expect(screen.getByRole("button", { name: "Restore workspace" })).toBeInTheDocument();
  expect(screen.queryByLabelText("Reason to suspend")).not.toBeInTheDocument();
});
