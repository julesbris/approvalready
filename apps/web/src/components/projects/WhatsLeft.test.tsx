import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { WhatsLeft } from "./WhatsLeft";

describe("WhatsLeft", () => {
  it("lists each step with its details and links to the first", () => {
    render(
      <WhatsLeft
        left={{
          done: false,
          items: [
            {
              step: "QUESTIONS",
              title: "Answer 7 more questions",
              count: 7,
              link_path: "/projects/p1/questionnaire",
              details: ["Lot and plan", "Storeys"],
            },
            {
              step: "TASKS",
              title: "Finish 1 task",
              count: 1,
              link_path: "/projects/p1#tasks-title",
              details: ["Ring the council"],
            },
          ],
        }}
      />,
    );
    expect(screen.getByText("2 steps", { exact: false })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Answer 7 more questions" }).getAttribute("href")).toBe(
      "/projects/p1/questionnaire",
    );
    expect(screen.getByText("and 5 more")).toBeTruthy();
    expect(screen.getByText("Ring the council")).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Pick up where you left off" }).getAttribute("href"),
    ).toBe("/projects/p1/questionnaire");
  });

  it("says when nothing is waiting", () => {
    render(<WhatsLeft left={{ done: true, items: [] }} />);
    expect(screen.getByText("Up to date")).toBeTruthy();
    expect(screen.queryByRole("link")).toBeNull();
  });
});
