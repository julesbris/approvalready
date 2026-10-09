import type { ProjectDetailOut, PropertyOut } from "@approvalready/shared-types";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { SitePanel, propertyLabel } from "./SitePanel";

const PROPERTY: PropertyOut = {
  id: "prop1",
  address: {
    line1: "1 Example St",
    line2: null,
    suburb: "Cairns",
    state: "QLD",
    postcode: "4870",
    lga_code: null,
  },
  relationships: ["OWNER"],
  lot_plan: "1RP000001",
  title_reference: null,
  land_area_m2: "640.5",
  created_at: "2026-10-09T00:00:00Z",
  updated_at: "2026-10-09T00:00:00Z",
};

const PROJECT = {
  id: "p1",
  vertical: "PLANNING",
  property_id: null,
} as unknown as ProjectDetailOut;

describe("SitePanel", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("labels a property by its address", () => {
    expect(propertyLabel(PROPERTY)).toBe("1 Example St, Cairns QLD 4870");
  });

  it("links an existing property to the project", async () => {
    const updated = { ...PROJECT, property_id: "prop1" };
    const fetchMock = vi.fn().mockResolvedValue(Response.json(updated));
    vi.stubGlobal("fetch", fetchMock);
    const onChange = vi.fn();
    render(
      <SitePanel
        organisationId="o1"
        project={PROJECT}
        properties={[PROPERTY]}
        canWrite
        onProjectChange={onChange}
      />,
    );
    fireEvent.change(screen.getByLabelText("Choose a property"), { target: { value: "prop1" } });
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(updated));
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/organisations/o1/projects/p1");
    expect(JSON.parse(init.body as string)).toEqual({ property_id: "prop1" });
  });

  it("adds a property and links it", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(Response.json(PROPERTY, { status: 201 }))
      .mockResolvedValueOnce(Response.json({ ...PROJECT, property_id: "prop1" }));
    vi.stubGlobal("fetch", fetchMock);
    render(
      <SitePanel
        organisationId="o1"
        project={PROJECT}
        properties={[]}
        canWrite
        onProjectChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Add a property" }));
    fireEvent.change(screen.getByLabelText("Street address"), { target: { value: "1 Example St" } });
    fireEvent.change(screen.getByLabelText("Suburb"), { target: { value: "Cairns" } });
    fireEvent.change(screen.getByLabelText("Postcode"), { target: { value: "4870" } });
    fireEvent.change(screen.getByLabelText("Land area in m² (optional)"), {
      target: { value: "640.5" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save property" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/organisations/o1/properties");
    expect(JSON.parse(init.body as string)).toEqual({
      address: {
        line1: "1 Example St",
        line2: null,
        suburb: "Cairns",
        state: "QLD",
        postcode: "4870",
      },
      lot_plan: null,
      land_area_m2: "640.5",
    });
  });

  it("shows the linked property read-only without write access", () => {
    render(
      <SitePanel
        organisationId="o1"
        project={{ ...PROJECT, property_id: "prop1" }}
        properties={[PROPERTY]}
        canWrite={false}
        onProjectChange={vi.fn()}
      />,
    );
    expect(screen.getByText("1 Example St, Cairns QLD 4870")).toBeInTheDocument();
    expect(screen.getByText("Lot and plan 1RP000001 · 640.5 m²")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add a property" })).not.toBeInTheDocument();
  });
});
