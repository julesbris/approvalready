import type {
  AddressMatchOut,
  ParcelOut,
  ProjectDetailOut,
  VesselLookupOut,
} from "@approvalready/shared-types";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { SitePanel } from "@/components/projects/SitePanel";
import { VesselPanel } from "@/components/projects/VesselPanel";

const MATCH: AddressMatchOut = {
  address_pid: 123,
  label: "34 Gilmore Street, Bentley Park QLD",
  line1: "34 Gilmore Street",
  suburb: "Bentley Park",
  state: "QLD",
  lot_plan: "1RP731159",
  lot_plan_label: "Lot 1 on RP731159",
  local_authority: "Cairns Regional",
  lga: "cairns",
  latitude: -17,
  longitude: 145.7,
};

const PARCEL: ParcelOut = {
  lot: "1",
  plan: "RP731159",
  lot_plan: "1RP731159",
  lot_plan_label: "Lot 1 on RP731159",
  tenure: "Freehold",
  land_area_m2: "774.00",
  locality: "Bentley Park",
  local_authority: "Cairns Regional",
  lga: "cairns",
  parcel_type: "Lot Type Parcel",
  overlays: [
    {
      key: "storm_tide_high",
      label: "Storm tide inundation area (high hazard)",
      group: "State coastal hazard mapping",
      constraint: "flooding",
      source_url: "https://example.test/11",
    },
  ],
  overlays_checked: ["State coastal hazard mapping", "State vegetation management mapping"],
  overlays_failed: [],
  not_checked: [{ label: "Bushfire prone area", why: "Not a service.", where_to_check: null }],
  source: "Queensland Government",
  source_url: "https://example.test/4",
  retrieved_at: "2026-10-09T00:00:00Z",
};

const VESSEL: VesselLookupOut = {
  uvi: "412345",
  name: "Reef Runner",
  displayed_identifier: "QF123",
  length_m: "12.4",
  fields: { UVI: "412345", "Vessel Name": "Reef Runner", Class: "1C" },
  source: "AMSA",
  source_url: "https://example.test/list.xlsx",
  list_retrieved_at: "2026-10-09T00:00:00Z",
  note: "Check it.",
};

function project(vertical: string) {
  return { id: "p1", vertical, property_id: null, vessel_id: null } as unknown as ProjectDetailOut;
}

function route(routes: Record<string, unknown>) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "POST") return Response.json({ id: "new" }, { status: 201 });
    const key = Object.keys(routes).find((k) => url.includes(k));
    return key ? Response.json(routes[key]) : Response.json({}, { status: 404 });
  });
}

describe("lookups", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("fills the property form from a picked Queensland address and shows its parcel", async () => {
    const fetchMock = route({
      "/lookups/addresses?q=34%20Gilmore": { matches: [MATCH], source: "QLD", note: "" },
      "/lookups/parcels/1RP731159": PARCEL,
    });
    vi.stubGlobal("fetch", fetchMock);
    render(
      <SitePanel
        organisationId="o1"
        project={project("PLANNING")}
        properties={[]}
        canWrite
        onProjectChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Add a property" }));
    fireEvent.change(screen.getByLabelText("Find a Queensland address"), {
      target: { value: "34 Gilmore" },
    });
    fireEvent.click(await screen.findByRole("button", { name: MATCH.label }));
    expect(screen.getByLabelText("Street address")).toHaveValue("34 Gilmore Street");
    expect(screen.getByLabelText("Suburb")).toHaveValue("Bentley Park");
    expect(screen.getByLabelText("Lot and plan (optional)")).toHaveValue("Lot 1 on RP731159");
    await waitFor(() =>
      expect(screen.getByLabelText("Land area in m² (optional)")).toHaveValue("774"),
    );
    expect(screen.getByText(/Storm tide inundation area/)).toBeInTheDocument();
    expect(screen.getByText(/Bushfire prone area/)).toBeInTheDocument();
  });

  it("fills the vessel form from AMSA's record for a UVI", async () => {
    vi.stubGlobal("fetch", route({ "/lookups/vessels/412345": VESSEL }));
    render(
      <VesselPanel
        organisationId="o1"
        project={project("VESSEL")}
        vessels={[]}
        canWrite
        onProjectChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Add a vessel" }));
    fireEvent.change(screen.getByLabelText("Start with the vessel's UVI"), {
      target: { value: "412345" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Look up" }));
    await waitFor(() => expect(screen.getByLabelText("Vessel name")).toHaveValue("Reef Runner"));
    expect(screen.getByLabelText("Overall length in metres (optional)")).toHaveValue("12.4");
    expect(screen.getByLabelText("UVI, if it has one")).toHaveValue("412345");
    expect(screen.getByText("1C")).toBeInTheDocument();
  });
});
