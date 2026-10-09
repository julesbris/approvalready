import type { BusinessProfileOut, ProjectDetailOut } from "@approvalready/shared-types";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { BusinessPanel, businessLabel } from "./BusinessPanel";

const BUSINESS = {
  id: "b1",
  legal_name: "Reef Cafe Pty Ltd",
  trading_name: "Reef Cafe",
  abn: "51824753556",
  acn: null,
  entity_type: "COMPANY",
  gst_registered: null,
  established_on: null,
  employee_band: "1_4",
  turnover_band: null,
  anzsic_code: null,
  address: null,
  created_at: "2026-10-09T00:00:00Z",
  updated_at: "2026-10-09T00:00:00Z",
} as BusinessProfileOut;

const PROJECT = {
  id: "p1",
  vertical: "BUSINESS",
  business_profile_id: null,
} as unknown as ProjectDetailOut;

describe("BusinessPanel", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("labels a business by its names and ABN", () => {
    expect(businessLabel(BUSINESS)).toBe("Reef Cafe (Reef Cafe Pty Ltd) · ABN 51 824 753 556");
    expect(businessLabel({ ...BUSINESS, trading_name: null, abn: null })).toBe(
      "Reef Cafe Pty Ltd",
    );
  });

  it("links an existing business to the project", async () => {
    const updated = { ...PROJECT, business_profile_id: "b1" };
    const fetchMock = vi.fn().mockResolvedValue(Response.json(updated));
    vi.stubGlobal("fetch", fetchMock);
    const onChange = vi.fn();
    render(
      <BusinessPanel
        organisationId="o1"
        project={PROJECT}
        businesses={[BUSINESS]}
        canWrite
        onProjectChange={onChange}
      />,
    );
    fireEvent.change(screen.getByLabelText("Choose a business"), { target: { value: "b1" } });
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(updated));
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/organisations/o1/projects/p1");
    expect(JSON.parse(init.body as string)).toEqual({ business_profile_id: "b1" });
  });

  it("adds a business without an address and links it", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(Response.json(BUSINESS, { status: 201 }))
      .mockResolvedValueOnce(Response.json({ ...PROJECT, business_profile_id: "b1" }));
    vi.stubGlobal("fetch", fetchMock);
    render(
      <BusinessPanel
        organisationId="o1"
        project={PROJECT}
        businesses={[]}
        canWrite
        onProjectChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Add a business" }));
    fireEvent.change(screen.getByLabelText("Legal name"), {
      target: { value: "Reef Cafe Pty Ltd" },
    });
    fireEvent.change(screen.getByLabelText("ABN (optional)"), {
      target: { value: "51 824 753 556" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save business" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/organisations/o1/business-profiles");
    expect(JSON.parse(init.body as string)).toMatchObject({
      legal_name: "Reef Cafe Pty Ltd",
      entity_type: "SOLE_TRADER",
      abn: "51 824 753 556",
      address: null,
    });
  });

  it("is read-only without write access", () => {
    render(
      <BusinessPanel
        organisationId="o1"
        project={{ ...PROJECT, business_profile_id: "b1" }}
        businesses={[BUSINESS]}
        canWrite={false}
        onProjectChange={vi.fn()}
      />,
    );
    expect(screen.getByText(/Reef Cafe \(Reef Cafe Pty Ltd\)/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
