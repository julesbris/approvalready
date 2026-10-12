import type { QuestionOut } from "@approvalready/shared-types";
import { render, screen, within } from "@testing-library/react";

import { QuestionField, optionGroups } from "./QuestionField";

const COUNCILS = [
  { value: "cairns", label: "Cairns Regional Council", group: "Queensland" },
  { value: "brisbane", label: "Brisbane City Council", group: "Queensland" },
  { value: "nsw_sydney", label: "City of Sydney Council", group: "New South Wales" },
  ...Array.from({ length: 7 }, (_, i) => ({
    value: `nsw_c${i}`,
    label: `Council ${i}`,
    group: "New South Wales",
  })),
  { value: "other", label: "A council not listed here", group: null },
];

describe("QuestionField", () => {
  it("splits options where their group changes", () => {
    const groups = optionGroups(COUNCILS);
    expect(groups.map(([heading, options]) => [heading, options.length])).toEqual([
      ["Queensland", 2],
      ["New South Wales", 8],
      [null, 1],
    ]);
  });

  it("shows grouped options under their state", () => {
    const question = {
      key: "property.lga",
      type: "SELECT",
      label: "Which council area is the site in?",
      help_text: null,
      required: false,
      options: COUNCILS,
    } as unknown as QuestionOut;
    render(
      <QuestionField
        question={question}
        value={null}
        text={undefined}
        error={undefined}
        disabled={false}
        onValue={() => {}}
        onText={() => {}}
      />,
    );
    const nsw = screen.getByRole("group", { name: "New South Wales" });
    expect(within(nsw).getByRole("option", { name: "City of Sydney Council" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "A council not listed here" })).toBeInTheDocument();
  });
});
