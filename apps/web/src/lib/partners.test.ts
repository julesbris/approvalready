import type { SessionOut } from "@approvalready/shared-types";

import {
  activePartnerOrganisation,
  areaLabel,
  formatCover,
  parseCover,
  partnerOrganisations,
} from "./partners";

describe("areaLabel", () => {
  it.each([
    [{ kind: "STATE", state: "QLD", value: "QLD" }, "All of QLD"],
    [{ kind: "POSTCODE", state: "QLD", value: "4870" }, "4870 QLD"],
    [{ kind: "LGA", state: "QLD", value: "Cairns" }, "Cairns (council area, QLD)"],
  ] as const)("%j -> %s", (area, expected) => {
    expect(areaLabel(area)).toBe(expected);
  });
});

describe("cover", () => {
  it.each([
    ["20000000", 2_000_000_000],
    ["$20,000,000", 2_000_000_000],
    [" 5 000 000 ", 500_000_000],
    ["0", null],
    ["", null],
    ["lots", null],
    ["12.5", null],
  ])("parses %j", (value, expected) => {
    expect(parseCover(value)).toBe(expected);
  });

  it("formats whole millions short", () => {
    expect(formatCover(2_000_000_000)).toBe("$20m");
    expect(formatCover(25_000_000)).toBe("$250,000");
  });
});

describe("partner organisations", () => {
  const session = {
    active_organisation_id: "p1",
    organisations: [
      { organisation_id: "c1", kind: "CUSTOMER" },
      { organisation_id: "p1", kind: "PARTNER" },
    ],
  } as unknown as SessionOut;

  it("finds the partner organisations and the active one", () => {
    expect(partnerOrganisations(session).map((o) => o.organisation_id)).toEqual(["p1"]);
    expect(activePartnerOrganisation(session)?.organisation_id).toBe("p1");
    expect(
      activePartnerOrganisation({ ...session, active_organisation_id: "c1" }),
    ).toBeNull();
  });
});
