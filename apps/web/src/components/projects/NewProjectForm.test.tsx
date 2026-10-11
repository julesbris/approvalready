import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { NewProjectForm } from "./NewProjectForm";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, refresh: vi.fn() }) }));

describe("NewProjectForm", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("asks which product area the project is about", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<NewProjectForm organisationId="o1" initialVertical={null} />);
    fireEvent.change(screen.getByLabelText(/Project name/), { target: { value: "Charter" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Choose what the project is about.");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("creates the project and goes straight into its questions", async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json({ id: "p9" }, { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<NewProjectForm organisationId="o1" initialVertical={null} />);
    fireEvent.click(screen.getByLabelText(/VesselReady/));
    fireEvent.change(screen.getByLabelText(/Project name/), { target: { value: "Charter" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/projects/p9/questionnaire"));
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/organisations/o1/projects");
    expect(JSON.parse(init.body as string)).toEqual({
      vertical: "VESSEL",
      title: "Charter",
      description: null,
    });
    expect((fetchMock.mock.calls[1] as [string])[0]).toBe(
      "/api/v1/organisations/o1/projects/p9/submissions",
    );
  });

  it("names the project after the product when no name is given", async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json({ id: "p9" }, { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<NewProjectForm organisationId="o1" initialVertical="VESSEL" />);
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() => expect(push).toHaveBeenCalled());
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string).title).toBe("VesselReady project");
  });

  it("opens the project page if the questions can't start", async () => {
    push.mockClear();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(Response.json({ id: "p9" }, { status: 201 }))
      .mockResolvedValueOnce(
        Response.json({ detail: { code: "x", message: "No questions." } }, { status: 409 }),
      );
    vi.stubGlobal("fetch", fetchMock);
    render(<NewProjectForm organisationId="o1" initialVertical="VESSEL" />);
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/projects/p9"));
  });
});
