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

  it("says where reminders arrive", () => {
    renderWorkspace();
    expect(screen.getByRole("link", { name: "notifications" })).toHaveAttribute(
      "href",
      "/notifications",
    );
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

  it("starts with one button that goes into the questions", async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json({ id: "s1" }, { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    renderWorkspace();
    expect(screen.getByText(/your result appears straight underneath/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Run/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Answer the questions" }));
    await vi.waitFor(() => expect(push).toHaveBeenCalledWith("/projects/p1/questionnaire"));
  });

  it("links to the answers and their result once assessed", () => {
    const submitted = {
      id: "s1",
      questionnaire_key: "planning.general",
      questionnaire_title: "Planning",
      version: 1,
      status: "SUBMITTED",
      submitted_at: "2026-10-04T00:00:00Z",
      updated_at: "2026-10-04T00:00:00Z",
    };
    const assessment = {
      id: "a1",
      project_id: "p1",
      submission_id: "s1",
      assessed_on: "2026-10-08",
      status: "COMPLETED",
      overall_confidence: "LIKELY",
      findings: 2,
      created_at: "2026-10-08T00:00:00Z",
    } as const;
    const { unmount } = renderWorkspace(true, {
      ...PROJECT,
      status: "ASSESSED",
      submissions: [submitted],
      latest_assessment: assessment,
    });
    expect(screen.getByRole("link", { name: "Assessed 8 Oct 2026" })).toHaveAttribute(
      "href",
      "/projects/p1/assessments/a1",
    );
    expect(screen.getByText(/Likely · 2 findings/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "See answers and result" })).toHaveAttribute(
      "href",
      "/projects/p1/questionnaire",
    );
    unmount();

    // Answers changed since: finishing them updates the result.
    renderWorkspace(true, {
      ...PROJECT,
      status: "ASSESSED",
      submissions: [{ ...submitted, status: "IN_PROGRESS", submitted_at: null }],
      latest_assessment: assessment,
    });
    expect(screen.getByText(/changed since the last result/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Finish and update my result" })).toBeInTheDocument();
  });

  it("is read-only without project.write", () => {
    renderWorkspace(false);
    expect(screen.queryByLabelText("Change status")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add task" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Answer the questions" })).not.toBeInTheDocument();
  });
});
