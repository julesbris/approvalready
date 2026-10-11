import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { GUIDES } from "@/lib/guides";
import {
  cardRef,
  fromBrisbaneInput,
  postStatusClass,
  timeInput,
  toBrisbaneInput,
} from "@/lib/marketing";

describe("marketing helpers", () => {
  it("reads and writes Brisbane time (UTC+10, no daylight saving)", () => {
    expect(fromBrisbaneInput("2026-10-12T09:00")).toBe("2026-10-11T23:00:00.000Z");
    expect(fromBrisbaneInput("2027-01-12T09:00")).toBe("2027-01-11T23:00:00.000Z");
    expect(fromBrisbaneInput("12/10/2026")).toBeNull();
    expect(toBrisbaneInput(new Date("2026-10-11T23:00:00Z"))).toBe("2026-10-12T09:00");
    expect(timeInput("09:30:00")).toBe("09:30");
  });

  it("only serves cards for guide-like names", () => {
    expect(cardRef("guide-cairns-subdivision.jpg")).toBe("guide-cairns-subdivision");
    expect(cardRef("../secret.jpg")).toBeNull();
    expect(cardRef("guide.png")).toBeNull();
  });

  it("colours every post status", () => {
    expect(postStatusClass("POSTED")).toBe("status status-completed");
    expect(postStatusClass("FAILED")).toBe("status status-failed");
  });
});

describe("the API's copy of the guide pages", () => {
  it("lists every public guide with the same title", () => {
    const file = path.resolve(__dirname, "../../../api/app/modules/marketing/web_guides.json");
    const copy = JSON.parse(readFileSync(file, "utf8")) as {
      guides: { slug: string; title: string; description: string }[];
    };
    expect(copy.guides.map((g) => [g.slug, g.title, g.description])).toEqual(
      GUIDES.map((g) => [g.slug, g.title, g.description]),
    );
  });
});
