import type {
  DocumentOut,
  EvidenceOut,
  EvidenceRequirementOut,
  GeneratedDocumentOut,
} from "@approvalready/shared-types";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { FileAnswer } from "@/components/questionnaire/FileAnswer";
import { formatBytes, waitUntil } from "@/lib/documents";

import { DocumentsPanel } from "./DocumentsPanel";
import { EvidencePanel } from "./EvidencePanel";
import { ReportDownloads } from "./ReportDownloads";

const DOC: DocumentOut = {
  id: "d1",
  project_id: "p1",
  filename: "site plan.pdf",
  content_type: "application/pdf",
  size_bytes: 2048,
  scan_status: "CLEAN",
  classification: "PRIVATE",
  created_at: "2026-10-09T00:00:00Z",
  created_by: "u1",
};

const REQUIREMENT = {
  id: "r1",
  finding_id: "f1",
  kind: "SITE_PLAN",
  title: "Site plan",
  detail: "Show the parking.",
  confidence: "VERIFIED",
} as EvidenceRequirementOut;

const REPORT: GeneratedDocumentOut = {
  id: "g1",
  project_id: "p1",
  assessment_id: "a1",
  format: "PDF",
  status: "PENDING",
  review_status: "NOT_REVIEWED",
  filename: "PLN-ABC123-assessment-2026-10-09.pdf",
  size_bytes: null,
  sha256: null,
  error: null,
  created_at: "2026-10-09T00:00:00Z",
  completed_at: null,
};

const file = (name = "photo.jpg") => new File(["x"], name, { type: "image/jpeg" });

describe("documents", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("formats sizes", () => {
    expect(formatBytes(500)).toBe("500 bytes");
    expect(formatBytes(2048)).toBe("2 KB");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB");
  });

  it("polls until background work is done, then stops", async () => {
    const states = ["PENDING", "PENDING", "CLEAN", "CLEAN"];
    const fetchOnce = vi.fn(async () => ({ ok: true as const, status: 200, data: states.shift() }));
    const result = await waitUntil(fetchOnce, (s) => s !== "PENDING", { intervalMs: 1 });
    expect(result).toMatchObject({ ok: true, data: "CLEAN" });
    expect(fetchOnce).toHaveBeenCalledTimes(3);
  });

  it("uploads files, waits for the virus check and links only clean files", async () => {
    const pending = { ...DOC, id: "d2", filename: "photo.jpg", scan_status: "PENDING" as const };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(Response.json(pending, { status: 201 }))
      .mockResolvedValueOnce(Response.json({ ...pending, scan_status: "CLEAN" }));
    vi.stubGlobal("fetch", fetchMock);
    render(
      <DocumentsPanel organisationId="o1" projectId="p1" documents={[DOC]} canWrite pollMs={1} />,
    );
    expect(screen.getByRole("link", { name: "site plan.pdf" })).toHaveAttribute(
      "href",
      "/api/v1/organisations/o1/documents/d1/content",
    );
    fireEvent.change(screen.getByLabelText(/Add files/), { target: { files: [file()] } });
    expect(await screen.findByRole("link", { name: "photo.jpg" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2); // the upload, then one status check
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/organisations/o1/projects/p1/documents");
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.headers as Record<string, string>)["content-type"]).toBeUndefined();
  });

  it("shows why an upload was refused", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        Response.json(
          { detail: { code: "file_rejected", message: "This file type isn't accepted." } },
          { status: 415 },
        ),
      ),
    );
    render(<DocumentsPanel organisationId="o1" projectId="p1" documents={[]} canWrite />);
    fireEvent.change(screen.getByLabelText(/Add files/), { target: { files: [file("x.exe")] } });
    expect(await screen.findByText("x.exe: This file type isn't accepted.")).toBeInTheDocument();
  });

  it("does not offer downloads of blocked files", () => {
    render(
      <DocumentsPanel
        organisationId="o1"
        projectId="p1"
        documents={[{ ...DOC, scan_status: "INFECTED" }]}
        canWrite={false}
      />,
    );
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText(/Blocked/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Add files/)).not.toBeInTheDocument();
  });

  it("attaches a project file as evidence", async () => {
    const evidence: EvidenceOut = {
      id: "e1",
      evidence_requirement_id: "r1",
      status: "SUBMITTED",
      note: null,
      review_note: null,
      reviewed_at: null,
      document: DOC,
      created_at: "2026-10-09T00:00:00Z",
    };
    const fetchMock = vi.fn().mockResolvedValue(Response.json(evidence, { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    render(
      <EvidencePanel
        organisationId="o1"
        projectId="p1"
        requirements={[REQUIREMENT]}
        evidence={[]}
        documents={[DOC]}
        canWrite
      />,
    );
    expect(screen.getByText("Nothing attached yet.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Attach a project file"), { target: { value: "d1" } });
    expect(await screen.findByText("Provided")).toBeInTheDocument();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/organisations/o1/evidence");
    expect(JSON.parse(init.body as string)).toEqual({
      evidence_requirement_id: "r1",
      uploaded_document_id: "d1",
    });
  });

  it("makes a report and offers the download when it is ready", async () => {
    const ready = { ...REPORT, status: "READY", size_bytes: 4096, completed_at: REPORT.created_at };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(Response.json(REPORT, { status: 202 }))
      .mockResolvedValueOnce(Response.json(ready));
    vi.stubGlobal("fetch", fetchMock);
    render(
      <ReportDownloads organisationId="o1" assessmentId="a1" generated={[]} canWrite pollMs={1} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Make PDF" }));
    const link = await screen.findByRole("link", { name: REPORT.filename });
    const href = "/api/v1/organisations/o1/generated-documents/g1/content";
    expect(link).toHaveAttribute("href", href);
    expect(JSON.parse((fetchMock.mock.calls[0] as [string, RequestInit])[1].body as string)).toEqual(
      { format: "PDF" },
    );
  });

  it("answers a FILE question with uploaded file ids", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(Response.json([DOC]))
      .mockResolvedValueOnce(Response.json({ ...DOC, id: "d3", filename: "survey.pdf" }));
    vi.stubGlobal("fetch", fetchMock);
    const onValue = vi.fn();
    const { rerender } = render(
      <FileAnswer
        id="q"
        organisationId="o1"
        projectId="p1"
        value={["d1"]}
        maxFiles={2}
        disabled={false}
        onValue={onValue}
      />,
    );
    expect(await screen.findByText(/site plan.pdf/)).toBeInTheDocument();
    fireEvent.change(document.getElementById("q")!, { target: { files: [file("survey.pdf")] } });
    await waitFor(() => expect(onValue).toHaveBeenCalledWith(["d1", "d3"]));
    rerender(
      <FileAnswer
        id="q"
        organisationId="o1"
        projectId="p1"
        value={["d1", "d3"]}
        maxFiles={2}
        disabled={false}
        onValue={onValue}
      />,
    );
    expect(screen.getByText(/most files this question takes/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Remove site plan.pdf" }));
    expect(onValue).toHaveBeenLastCalledWith(["d3"]);
  });
});
