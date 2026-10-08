import type { ProjectDetailOut } from "@approvalready/shared-types";
import { fireEvent, render, screen, within } from "@testing-library/react";

import { ProjectWorkspace } from "./ProjectWorkspace";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, refresh: vi.fn() }) }));

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
};

function renderWorkspace(canWrite = true) {
  return render(
    <ProjectWorkspace
      organisationId="o1"
      project={PROJECT}
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
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        Response.json({ ...PROJECT, status: "IN_PROGRESS", allowed_status_changes: ["ARCHIVED", "COMPLETED"] }),
      );
    vi.stubGlobal("fetch", fetchMock);
    renderWorkspace();
    expect(screen.getByText("PlanningReady · Reference PLN-7K2M9Q")).toBeInTheDocument();
    const actions = screen.getByLabelText("Change status");
    expect(within(actions).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "Archive",
      "Mark as in progress",
    ]);
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
    fireEvent.change(screen.getByLabelText("Task"), { target: { value: "Book a surveyor" } });
    fireEvent.click(screen.getByRole("button", { name: "Add task" }));
    expect(await screen.findByLabelText("Book a surveyor")).not.toBeChecked();
  });

  it("is read-only without project.write", () => {
    renderWorkspace(false);
    expect(screen.queryByLabelText("Change status")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add task" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Answer the questions" })).not.toBeInTheDocument();
  });
});
