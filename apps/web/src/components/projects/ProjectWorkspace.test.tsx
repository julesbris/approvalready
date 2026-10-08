import type { ProjectDetailOut } from "@approvalready/shared-types";
import { fireEvent, render, screen, within } from "@testing-library/react";

import { ProjectWorkspace } from "./ProjectWorkspace";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, refresh: vi.fn() }),
}));

const PROJECT: ProjectDetailOut = {
  id: "p1",
  organisation_id: "o1",
  reference_code: "PLN-7K2M9Q",
  vertical: "PLANNING",
  title: "Granny flat",
  description: null,
  status: "DRAFT",
  allowed_status_changes: ["ARCHIVED", "IN_PROGRESS"],
  property_id: null,
  vessel_id: null,
  business_profile_id: null,
  created_at: "2026-10-04T00:00:00Z",
  updated_at: "2026-10-04T00:00:00Z",
  submissions: [],
  open_tasks: 0,
  latest_assessment: null,
};

function renderWorkspace(canWrite = true, project: ProjectDetailOut = PROJECT) {
  return render(
    <ProjectWorkspace
      organisationId="o1"
      project={project}
      tasks={[]}
      reminders={[]}
      members={[]}
      currentUserId="u1"
      canWrite={canWrite}
    />,
  );
}

describe("ProjectWorkspace", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("offers only the status changes the API allows", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      Response.json({
        ...PROJECT,
        status: "IN_PROGRESS",
        allowed_status_changes: ["ARCHIVED", "COMPLETED"],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderWorkspace();
    expect(screen.getByText("PlanningReady · Reference PLN-7K2M9Q")).toBeInTheDocument();
    const actions = screen.getByLabelText("Change status");
    expect(
      within(actions)
        .getAllByRole("button")
        .map((b) => b.textContent),
    ).toEqual(["Archive", "Mark as in progress"]);
    fireEvent.click(screen.getByRole("button", { name: "Mark as in progress" }));
    expect(await screen.findByRole("button", { name: "Mark as completed" })).toBeInTheDocument();
    expect(screen.getAllByText("In progress").length).toBeGreaterThan(0);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/organisations/o1/projects/p1/status");
    expect(JSON.parse(init.body as string)).toEqual({ status: "IN_PROGRESS" });
  });

  it("is honest that reminder delivery isn't switched on yet", () => {
    renderWorkspace();
    expect(screen.getByText(/don.t rely on them for deadlines yet/)).toBeInTheDocument();
  });

  it("adds a task", async () => {
    const task = {
      id: "t1",
      project_id: "p1",
      title: "Book a surveyor",
      notes: null,
      status: "OPEN",
      source: "USER",
      due_on: null,
      assignee_user_id: null,
      completed_at: null,
      created_at: "2026-10-04T00:00:00Z",
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(task, { status: 201 })));
    renderWorkspace();
    fireEvent.change(screen.getByLabelText("Task"), {
      target: { value: "Book a surveyor" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add task" }));
    expect(await screen.findByLabelText("Book a surveyor")).not.toBeChecked();
  });

  it("runs an assessment once answers are submitted", async () => {
    renderWorkspace();
    expect(screen.getByRole("button", { name: "Run assessment" })).toBeDisabled();
    expect(screen.getByText("Submit your answers first.")).toBeInTheDocument();
  });

  it("opens the new assessment after running it", async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json({ id: "a2" }, { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    renderWorkspace(true, {
      ...PROJECT,
      status: "ASSESSED",
      submissions: [
        {
          id: "s1",
          questionnaire_key: "planning.general",
          questionnaire_title: "Planning",
          version: 1,
          status: "SUBMITTED",
          submitted_at: "2026-10-04T00:00:00Z",
          updated_at: "2026-10-04T00:00:00Z",
        },
      ],
      latest_assessment: {
        id: "a1",
        project_id: "p1",
        submission_id: "s1",
        assessed_on: "2026-10-08",
        status: "COMPLETED",
        overall_confidence: "LIKELY",
        findings: 2,
        created_at: "2026-10-08T00:00:00Z",
      },
    });
    expect(screen.getByRole("link", { name: "Assessed 8 Oct 2026" })).toHaveAttribute(
      "href",
      "/projects/p1/assessments/a1",
    );
    expect(screen.getByText(/Likely · 2 findings/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Run a new assessment" }));
    await vi.waitFor(() => expect(push).toHaveBeenCalledWith("/projects/p1/assessments/a2"));
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/v1/organisations/o1/projects/p1/assessments");
  });

  it("is read-only without project.write", () => {
    renderWorkspace(false);
    expect(screen.queryByLabelText("Change status")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add task" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Answer the questions" })).not.toBeInTheDocument();
  });
});
