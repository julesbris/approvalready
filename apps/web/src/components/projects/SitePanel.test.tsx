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
    fireEvent.change(screen.getByLabelText("Bedrooms"), { target: { value: "3" } });
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
        latitude: null,
        longitude: null,
      },
      lot_plan: null,
      land_area_m2: "640.5",
      bedrooms: 3,
      bathrooms: null,
      car_spaces: null,
      property_type: null,
      listing_url: null,
    });
  });

  it("brings a property in from a listing link", async () => {
    const listing = {
      site: "domain",
      site_name: "Domain",
      how: "Domain has an official developer API.",
      url: "https://www.domain.com.au/1-example-street-cairns-qld-4870-2019123456",
      address_text: "1 Example Street Cairns QLD 4870",
      property_type: "House",
      details: {
        bedrooms: 3,
        bathrooms: 2,
        car_spaces: 1,
        property_type: "House",
        price_text: "Offers over $650,000",
        headline: null,
        status: "live",
        objective: "sale",
      },
      matches: [
        {
          address_pid: 1,
          label: "1 Example Street Cairns QLD",
          line1: "1 Example Street",
          suburb: "Cairns",
          state: "QLD",
          postcode: "4870",
          lot_plan: null,
          lot_plan_label: null,
          local_authority: "Cairns Regional",
          lga: "cairns",
          latitude: -16.9,
          longitude: 145.7,
        },
      ],
      note: "Pick the matching address to fill in the rest.",
    };
    const fetchMock = vi.fn().mockResolvedValueOnce(Response.json(listing));
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
    fireEvent.change(screen.getByLabelText("Have a listing? Paste its link"), {
      target: { value: listing.url },
    });
    fireEvent.click(screen.getByRole("button", { name: "Bring it in" }));
    await waitFor(() =>
      expect(screen.getByLabelText("Street address")).toHaveValue("1 Example Street"),
    );
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/organisations/o1/lookups/listing");
    expect(screen.getByLabelText("Bedrooms")).toHaveValue("3");
    expect(screen.getByLabelText("Bathrooms")).toHaveValue("2");
    expect(screen.getByText(/House · 3 bed, 2 bath, 1 car · Offers over \$650,000/)).toBeInTheDocument();
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
