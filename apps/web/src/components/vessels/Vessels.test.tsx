import type {
  CertificateOut,
  ChecklistOut,
  GeneratedDocumentOut,
  ProjectDetailOut,
  SmsOut,
  VesselOut,
} from "@approvalready/shared-types";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { REPORT_TEMPLATES, ReportDownloads } from "@/components/documents/ReportDownloads";
import { ChecklistsPanel } from "@/components/projects/ChecklistsPanel";
import { VesselPanel, vesselLabel } from "@/components/projects/VesselPanel";

import { SmsBuilder } from "./SmsBuilder";

const VESSEL = {
  id: "v1",
  name: "Reef Runner",
  vessel_type: "MOTOR",
  length_m: "11.50",
  uvi: "ABC123",
} as unknown as VesselOut;

const PROJECT = { id: "p1", vertical: "VESSEL", vessel_id: "v1" } as unknown as ProjectDetailOut;

const CERTIFICATE = {
  id: "c1",
  vessel_id: "v1",
  kind: "CERTIFICATE_OF_SURVEY",
  number: "12345",
  issuer: "AMSA",
  expires_on: "2026-11-01",
  state: "EXPIRING",
} as unknown as CertificateOut;

const CHECKLIST: ChecklistOut = {
  id: "cl1",
  project_id: "p1",
  key: "vessel.uvi",
  title: "Unique Vessel Identifier (UVI)",
  description: "Getting and displaying a UVI.",
  sources: [{ title: "Obtain a UVI", organisation: "AMSA", url: "https://www.amsa.gov.au/uvi" }],
  origin: "RULE",
  finding_id: "f1",
  done: 0,
  total: 2,
  created_at: "2026-10-09T00:00:00Z",
  items: [
    {
      id: "i1",
      checklist_id: "cl1",
      key: "display",
      title: "Display the UVI",
      detail: null,
      required: true,
      status: "OPEN",
      note: null,
      completed_at: null,
      completed_by: null,
    },
    {
      id: "i2",
      checklist_id: "cl1",
      key: "notify",
      title: "Tell AMSA if you sell",
      detail: null,
      required: false,
      status: "OPEN",
      note: null,
      completed_at: null,
      completed_by: null,
    },
  ],
};

const ELEMENT = {
  key: "vessel_details",
  title: "Vessel details",
  guidance: "Owner and vessel.",
  required: true,
  text: null,
  suggestion: "Reef Runner is a motor vessel.",
};

const SMS: SmsOut = {
  project_id: "p1",
  title: "Safety management system",
  description: "Every DCV needs one.",
  disclaimer: "This is your own document.",
  sources: [{ title: "Marine Order 504", organisation: "AMSA", url: "https://example.com/mo504" }],
  sections: [
    {
      key: "about",
      title: "About the vessel",
      elements: [ELEMENT],
    },
  ],
  written: 0,
  required: 1,
  saved_at: null,
  outdated_structure: false,
};

describe("VesselReady", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("labels a vessel and lists its certificates with expiry", async () => {
    expect(vesselLabel(VESSEL)).toBe("Reef Runner (Motor boat, 11.5 m) · UVI ABC123");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json([CERTIFICATE])));
    render(
      <VesselPanel
        organisationId="o1"
        project={PROJECT}
        vessels={[VESSEL]}
        canWrite
        onProjectChange={vi.fn()}
      />,
    );
    expect(await screen.findByText("Certificate of survey")).toBeInTheDocument();
    expect(screen.getByText(/Expires soon · expires 1 Nov 2026/)).toBeInTheDocument();
  });

  it("ticks an item and asks why a required item doesn't apply", async () => {
    const done = { ...CHECKLIST.items[0], status: "DONE", completed_at: "2026-10-09T01:00:00Z" };
    const fetchMock = vi.fn().mockResolvedValue(Response.json(done));
    vi.stubGlobal("fetch", fetchMock);
    render(
      <ChecklistsPanel
        organisationId="o1"
        projectId="p1"
        checklists={[CHECKLIST]}
        definitions={[]}
        canWrite
      />,
    );
    fireEvent.click(screen.getByRole("checkbox", { name: "Display the UVI" }));
    expect(await screen.findByText("1 of 2 done")).toBeInTheDocument();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/organisations/o1/checklist-items/i1");
    expect(JSON.parse(init.body as string)).toEqual({ status: "DONE" });
    expect(screen.queryByText("Remove this checklist")).not.toBeInTheDocument();
  });

  it("offers the vessel details as a starting text and saves a section", async () => {
    const saved = {
      ...SMS,
      written: 1,
      saved_at: "2026-10-09T01:00:00Z",
      sections: [
        {
          key: "about",
          title: "About the vessel",
          elements: [{ ...ELEMENT, text: "Reef Runner is a motor vessel." }],
        },
      ],
    };
    const fetchMock = vi.fn().mockResolvedValue(Response.json(saved));
    vi.stubGlobal("fetch", fetchMock);
    render(
      <SmsBuilder
        organisationId="o1"
        projectId="p1"
        latestAssessmentId={null}
        sms={SMS}
        canWrite
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Start from your vessel's details" }));
    expect(screen.getByLabelText("Vessel details")).toHaveValue("Reef Runner is a motor vessel.");
    fireEvent.click(screen.getByRole("button", { name: "Save this section" }));
    expect(await screen.findByText(/1 of 1 required parts written/)).toBeInTheDocument();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/organisations/o1/projects/p1/sms");
    expect(JSON.parse(init.body as string)).toEqual({
      content: { vessel_details: "Reef Runner is a motor vessel." },
    });
  });

  it("makes the SMS report separately from the pathway", async () => {
    const report = {
      id: "g1",
      project_id: "p1",
      assessment_id: "a1",
      template_key: "SMS",
      format: "HTML",
      status: "READY",
      review_status: "NOT_REVIEWED",
      filename: "VSL-1-safety-management-system-2026-10-09.html",
      size_bytes: 100,
      sha256: null,
      error: null,
      created_at: "2026-10-09T00:00:00Z",
      completed_at: "2026-10-09T00:00:00Z",
    } as GeneratedDocumentOut;
    const fetchMock = vi.fn().mockResolvedValue(Response.json(report, { status: 202 }));
    vi.stubGlobal("fetch", fetchMock);
    render(
      <ReportDownloads
        organisationId="o1"
        assessmentId="a1"
        generated={[]}
        canWrite
        templates={REPORT_TEMPLATES.VESSEL}
        pollMs={1}
      />,
    );
    expect(screen.getByText("Approvals pathway")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Make Safety management system (draft) as Web page (HTML)" }),
    );
    expect(await screen.findByRole("link", { name: report.filename })).toBeInTheDocument();
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({ format: "HTML", template: "SMS" });
    await waitFor(() => expect(screen.getAllByRole("link")).toHaveLength(1));
  });
});
